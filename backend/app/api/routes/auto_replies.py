from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from app.api.dependencies import CurrentUser, CsrfProtectedUser, DatabaseSession
from app.schemas.auto_reply import (
    AutoReplyActivityPage,
    AutoReplyActivityRead,
    AutoReplySettingsRead,
    AutoReplySettingsUpdate,
)
from app.services import auto_reply

router = APIRouter(prefix="/auto-replies", tags=["Automatic replies"])


def _read_settings(session, user) -> AutoReplySettingsRead:
    settings = auto_reply.get_settings(session, user)
    connected, compose_enabled = auto_reply.account_capabilities(session, user)
    mode = "off" if not settings.enabled else (
        "automatic_send" if settings.automatic_sending_enabled else "draft"
    )
    return AutoReplySettingsRead(
        enabled=settings.enabled,
        automatic_sending_enabled=settings.automatic_sending_enabled,
        mode=mode,
        interval_minutes=settings.interval_minutes,
        daily_limit=settings.daily_limit,
        reply_required_only=settings.reply_required_only,
        exclude_sensitive=settings.exclude_sensitive,
        allowed_senders=settings.allowed_senders or [],
        blocked_senders=settings.blocked_senders or [],
        include_keywords=settings.include_keywords or [],
        exclude_keywords=settings.exclude_keywords or [],
        next_run_at=settings.next_run_at,
        gmail_connected=connected,
        compose_enabled=compose_enabled,
    )


@router.get("/settings", response_model=AutoReplySettingsRead)
def settings_read(session: DatabaseSession, user: CurrentUser) -> AutoReplySettingsRead:
    return _read_settings(session, user)


@router.patch("/settings", response_model=AutoReplySettingsRead)
def settings_update(
    payload: AutoReplySettingsUpdate,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> AutoReplySettingsRead:
    values = payload.model_dump(exclude_unset=True)
    connected, compose_enabled = auto_reply.account_capabilities(session, user)
    if values.get("enabled") is True and (not connected or not compose_enabled):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect Gmail and enable Gmail draft access before activating automatic replies",
        )
    try:
        auto_reply.update_settings(session, user, values)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _read_settings(session, user)


@router.post("/emergency-off", response_model=AutoReplySettingsRead)
def emergency_off(session: DatabaseSession, user: CsrfProtectedUser) -> AutoReplySettingsRead:
    auto_reply.emergency_off(session, user)
    return _read_settings(session, user)


@router.get("/activity", response_model=AutoReplyActivityPage)
def activity_list(
    session: DatabaseSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AutoReplyActivityPage:
    items, total = auto_reply.list_activity(session, user, page=page, page_size=page_size)
    return AutoReplyActivityPage(
        items=[AutoReplyActivityRead(
            id=item.id,
            email_id=item.email_id,
            email_subject=item.email.subject,
            email_sender=item.email.sender,
            status=item.status,
            reason_code=item.reason_code,
            gmail_draft_id=item.gmail_draft_id,
            gmail_message_id=item.gmail_message_id,
            created_at=item.created_at,
        ) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )
