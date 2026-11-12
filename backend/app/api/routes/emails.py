from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.dependencies import CurrentUser, CsrfProtectedUser, DatabaseSession
from app.schemas.email import EmailListResponse, EmailPatch, EmailRead
from app.schemas.gmail import GmailThreadRead
from app.models import Email
from app.services.emails import get_email, list_emails, update_email
from app.services.gmail import (
    GmailAPIUnavailable,
    GmailRateLimited,
    GmailReauthorizationRequired,
    get_gmail_account,
    sync_thread,
)

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("", response_model=EmailListResponse)
def emails_list(
    session: DatabaseSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    unread: bool | None = None,
    sent: bool | None = None,
    starred: bool | None = None,
    priority: bool | None = None,
) -> EmailListResponse:
    connected_gmail = get_gmail_account(session, user)
    source = "gmail" if connected_gmail is not None else "sample"
    return EmailListResponse(
        **list_emails(
            session,
            user,
            source=source,
            page=page,
            page_size=page_size,
            search=search,
            unread=unread,
            sent=sent,
            starred=starred,
            priority=priority,
        )
    )


@router.get("/{email_id}", response_model=EmailRead)
def email_detail(
    email_id: UUID, session: DatabaseSession, user: CurrentUser
) -> EmailRead:
    email = get_email(session, user, email_id)
    if email is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    return EmailRead.model_validate(email)


@router.patch("/{email_id}", response_model=EmailRead)
def email_update(
    email_id: UUID,
    payload: EmailPatch,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> EmailRead:
    changes = payload.changes()
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one email property must be provided",
        )
    email = get_email(session, user, email_id)
    if email is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    if email.source == "gmail":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gmail messages are read-only in this phase",
        )
    return EmailRead.model_validate(update_email(session, email, changes))


@router.get("/{email_id}/thread", response_model=GmailThreadRead)
def email_thread(
    email_id: UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> GmailThreadRead:
    email = get_email(session, user, email_id)
    if email is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    if not email.thread_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Email thread not found"
        )

    messages = []
    account = get_gmail_account(session, user)
    if email.source == "gmail" and account and account.status == "connected":
        try:
            messages = sync_thread(session, user, account, email.thread_id)
        except GmailReauthorizationRequired as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Gmail authorization expired or was revoked; reconnect Gmail",
            ) from error
        except GmailRateLimited as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Gmail rate limit reached; try again shortly",
            ) from error
        except GmailAPIUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gmail thread could not be loaded",
            ) from error

    if not messages:
        messages = list(
            session.scalars(
                select(Email)
                .where(
                    Email.user_id == user.id,
                    Email.source == email.source,
                    Email.thread_id == email.thread_id,
                )
                .order_by(Email.received_at.asc().nullslast(), Email.created_at.asc())
                .limit(100)
            )
        )
    return GmailThreadRead(
        messages=[EmailRead.model_validate(message) for message in messages]
    )
