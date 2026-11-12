from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select

from app.api.dependencies import CsrfProtectedUser, CurrentUser, DatabaseSession
from app.core.config import ConfigurationError
from app.models import ConnectedAccount, Draft
from app.schemas.draft import DraftRead, GmailDraftRequest
from app.schemas.gmail import (
    GmailDraftsResponse,
    GmailSendRequest,
    GmailSendStatusRead,
)
from app.services.gmail import (
    GmailError,
    GmailHistoryExpired,
    GmailNotConnected,
    GmailRateLimited,
    GmailReauthorizationRequired,
    GmailWriteOutcomeUnknown,
    GmailWriteRejected,
    build_gmail_raw_message,
    build_gmail_service,
    create_remote_gmail_draft,
    delete_remote_gmail_draft,
    get_remote_gmail_draft,
    list_remote_gmail_drafts,
    parsed_gmail_draft,
    record_sent_gmail_message,
    require_gmail_compose_account,
    send_remote_gmail_draft,
    update_remote_gmail_draft,
)

router = APIRouter(
    prefix="/integrations/gmail/drafts",
    tags=["Gmail drafts"],
)
logger = logging.getLogger(__name__)
MAX_GMAIL_DRAFTS_TO_SYNC = 100


def _http_error(error: GmailError | ConfigurationError) -> HTTPException:
    if isinstance(error, ConfigurationError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gmail integration is not configured",
        )
    if isinstance(error, GmailNotConnected):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect Gmail before managing Gmail drafts",
        )
    if isinstance(error, GmailReauthorizationRequired):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gmail compose permission is unavailable; reconnect Gmail",
        )
    if isinstance(error, GmailRateLimited):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Gmail rate limit reached; try again shortly",
        )
    if isinstance(error, GmailHistoryExpired):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The Gmail draft no longer exists",
        )
    if isinstance(error, GmailWriteRejected):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gmail rejected the requested draft operation",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Gmail draft operation failed or could not be confirmed",
    )


def _load_owned_draft(session: DatabaseSession, user: CurrentUser, draft_id: UUID) -> Draft:
    draft = session.scalar(
        select(Draft).where(
            Draft.id == draft_id,
            Draft.user_id == user.id,
            Draft.gmail_draft_id.is_not(None),
        )
    )
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Gmail draft not found"
        )
    return draft


def _apply_request(draft: Draft, payload: GmailDraftRequest) -> None:
    data = payload.model_dump()
    draft.recipients = data["recipients"]
    draft.cc = data["cc"]
    draft.bcc = data["bcc"]
    draft.recipient = ", ".join(data["recipients"])
    draft.subject = data["subject"]
    draft.body = data["body"]


def _sync_remote_draft(
    session: DatabaseSession,
    user: CurrentUser,
    service,
    gmail_draft_id: str,
) -> Draft | None:
    wrapper = get_remote_gmail_draft(service, gmail_draft_id)
    message = wrapper.get("message")
    if not isinstance(message, dict):
        return None
    draft = session.scalar(
        select(Draft).where(
            Draft.user_id == user.id,
            Draft.gmail_draft_id == gmail_draft_id,
        )
    )
    if draft is None:
        draft = Draft(
            user_id=user.id,
            status="draft",
            send_status="not_sent",
            gmail_draft_id=gmail_draft_id,
        )
        session.add(draft)
    parsed = parsed_gmail_draft(message)
    draft.recipients = parsed["recipients"]
    draft.cc = parsed["cc"]
    draft.bcc = parsed["bcc"]
    draft.recipient = parsed["recipient"]
    draft.subject = parsed["subject"]
    draft.body = parsed["body"]
    draft.gmail_message_id = parsed["gmail_message_id"]
    return draft


@router.get("", response_model=GmailDraftsResponse)
def list_gmail_drafts(
    session: DatabaseSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> GmailDraftsResponse:
    try:
        account = require_gmail_compose_account(session, user)
        service = build_gmail_service(account, session)
        refs = list_remote_gmail_drafts(service, MAX_GMAIL_DRAFTS_TO_SYNC)
        for ref in refs:
            draft_id = ref.get("id")
            if isinstance(draft_id, str):
                _sync_remote_draft(session, user, service, draft_id)
        session.commit()
    except (GmailError, ConfigurationError) as error:
        session.rollback()
        raise _http_error(error) from error

    statement = select(Draft).where(
        Draft.user_id == user.id,
        Draft.gmail_draft_id.is_not(None),
        or_(
            Draft.gmail_draft_id.in_(
                [
                    draft_ref["id"]
                    for draft_ref in refs
                    if isinstance(draft_ref.get("id"), str)
                ]
            ),
            Draft.send_status.in_(("unknown", "sending", "failed")),
        ),
    )
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = session.scalars(
        statement.order_by(Draft.updated_at.desc(), Draft.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return GmailDraftsResponse(
        items=[DraftRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=DraftRead, status_code=status.HTTP_201_CREATED)
def create_gmail_draft(
    payload: GmailDraftRequest,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> DraftRead:
    try:
        account = require_gmail_compose_account(session, user)
        raw_message = build_gmail_raw_message(**payload.model_dump())
        result = create_remote_gmail_draft(
            build_gmail_service(account, session), raw_message
        )
        gmail_draft_id = result.get("id")
        message = result.get("message")
        if not isinstance(gmail_draft_id, str) or not isinstance(message, dict):
            raise GmailWriteOutcomeUnknown
        draft = Draft(
            user_id=user.id,
            status="draft",
            send_status="not_sent",
            gmail_draft_id=gmail_draft_id,
        )
        draft_data = parsed_gmail_draft(message)
        draft.recipients = payload.recipients
        draft.cc = payload.cc
        draft.bcc = payload.bcc
        draft.recipient = ", ".join(payload.recipients)
        draft.subject = payload.subject
        draft.body = payload.body
        draft.gmail_message_id = draft_data["gmail_message_id"]
        session.add(draft)
        session.commit()
        session.refresh(draft)
    except (GmailError, ConfigurationError) as error:
        session.rollback()
        raise _http_error(error) from error
    return DraftRead.model_validate(draft)


@router.get("/{draft_id}", response_model=DraftRead)
def get_gmail_draft(
    draft_id: UUID, session: DatabaseSession, user: CurrentUser
) -> DraftRead:
    draft = _load_owned_draft(session, user, draft_id)
    try:
        account = require_gmail_compose_account(session, user)
        service = build_gmail_service(account, session)
        _sync_remote_draft(session, user, service, draft.gmail_draft_id)
        session.commit()
        session.refresh(draft)
    except (GmailError, ConfigurationError) as error:
        session.rollback()
        raise _http_error(error) from error
    return DraftRead.model_validate(draft)


@router.put("/{draft_id}", response_model=DraftRead)
def update_gmail_draft(
    draft_id: UUID,
    payload: GmailDraftRequest,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> DraftRead:
    draft = _load_owned_draft(session, user, draft_id)
    if draft.send_status not in {"not_sent", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A draft with a send attempt cannot be edited",
        )
    try:
        account = require_gmail_compose_account(session, user)
        raw_message = build_gmail_raw_message(**payload.model_dump())
        result = update_remote_gmail_draft(
            build_gmail_service(account, session), draft.gmail_draft_id, raw_message
        )
        message = result.get("message")
        if not isinstance(message, dict):
            raise GmailWriteOutcomeUnknown
        _apply_request(draft, payload)
        draft.gmail_message_id = parsed_gmail_draft(message)["gmail_message_id"]
        draft.send_status = "not_sent"
        session.commit()
        session.refresh(draft)
    except (GmailError, ConfigurationError) as error:
        session.rollback()
        raise _http_error(error) from error
    return DraftRead.model_validate(draft)


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gmail_draft(
    draft_id: UUID, session: DatabaseSession, user: CsrfProtectedUser
) -> Response:
    draft = _load_owned_draft(session, user, draft_id)
    if draft.send_status not in {"not_sent", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A draft with a send attempt cannot be deleted",
        )
    try:
        account = require_gmail_compose_account(session, user)
        delete_remote_gmail_draft(
            build_gmail_service(account, session), draft.gmail_draft_id
        )
        session.delete(draft)
        session.commit()
    except (GmailError, ConfigurationError) as error:
        session.rollback()
        raise _http_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{draft_id}/send", response_model=GmailSendStatusRead)
def send_gmail_draft(
    draft_id: UUID,
    payload: GmailSendRequest,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> GmailSendStatusRead:
    draft = session.scalar(
        select(Draft)
        .where(
            Draft.id == draft_id,
            Draft.user_id == user.id,
            Draft.gmail_draft_id.is_not(None),
        )
        .with_for_update()
    )
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Gmail draft not found"
        )
    if draft.send_status not in {"not_sent", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Draft cannot be sent again (current status: {draft.send_status})",
        )

    draft.send_status = "sending"
    session.commit()
    try:
        account = require_gmail_compose_account(session, user)
        result = send_remote_gmail_draft(
            build_gmail_service(account, session), draft.gmail_draft_id
        )
        message_id = result.get("id")
        if not isinstance(message_id, str) or not message_id:
            raise GmailWriteOutcomeUnknown
        draft = session.scalar(
            select(Draft).where(Draft.id == draft_id, Draft.user_id == user.id)
        )
        if draft is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Gmail draft not found"
            )
        draft.gmail_message_id = message_id
        draft.send_status = "sent"
        thread_id = result.get("threadId")
        record_sent_gmail_message(
            session,
            user,
            account,
            draft,
            message_id,
            thread_id if isinstance(thread_id, str) else None,
        )
        session.commit()
    except GmailWriteOutcomeUnknown as error:
        session.rollback()
        draft = session.scalar(
            select(Draft).where(Draft.id == draft_id, Draft.user_id == user.id)
        )
        if draft is not None:
            draft.send_status = "unknown"
            session.commit()
        logger.warning("Gmail send result could not be confirmed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gmail could not confirm whether the message was sent; do not retry",
        ) from error
    except (GmailError, ConfigurationError) as error:
        session.rollback()
        draft = session.scalar(
            select(Draft).where(Draft.id == draft_id, Draft.user_id == user.id)
        )
        if draft is not None:
            draft.send_status = "failed"
            session.commit()
        raise _http_error(error) from error
    return GmailSendStatusRead(
        draft_id=draft.id,
        status=draft.send_status,
        gmail_message_id=draft.gmail_message_id,
    )


@router.get("/{draft_id}/send-status", response_model=GmailSendStatusRead)
def gmail_draft_send_status(
    draft_id: UUID, session: DatabaseSession, user: CurrentUser
) -> GmailSendStatusRead:
    draft = _load_owned_draft(session, user, draft_id)
    return GmailSendStatusRead(
        draft_id=draft.id,
        status=draft.send_status,
        gmail_message_id=draft.gmail_message_id,
    )
