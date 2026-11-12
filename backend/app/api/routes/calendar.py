from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, CsrfProtectedUser, DatabaseSession
from app.core.config import (
    ConfigurationError,
    get_calendar_oauth_config,
    get_cookie_samesite,
    get_cookie_secure,
    get_frontend_url,
)
from app.database.session import get_db
from app.models import ConnectedAccount, OAuthTransaction
from app.schemas.calendar import (
    CalendarAvailabilityRead,
    CalendarAvailabilityRequest,
    CalendarConnectRead,
    CalendarConflictRead,
    CalendarConflictRequest,
    CalendarDeleteRequest,
    CalendarEventCreate,
    CalendarEventPage,
    CalendarEventRead,
    CalendarEventUpdate,
    CalendarEventWrite,
    CalendarListRead,
    CalendarStatusRead,
    MeetingAssistantRead,
    MeetingAssistantRequest,
)
from app.services import ai as ai_service
from app.services.auth import (
    GoogleIdentityError,
    OAuthStateError,
    consume_oauth_transaction,
    create_oauth_transaction,
    token_digest,
)
from app.services.calendar import (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_LIST_SCOPE,
    CALENDAR_PROVIDER,
    CALENDAR_SCOPES,
    CalendarError,
    CalendarEventAlreadyExists,
    CalendarEventNotFound,
    CalendarNotConnected,
    CalendarRateLimited,
    CalendarReauthorizationRequired,
    CalendarWriteOutcomeUnknown,
    build_calendar_service,
    calendar_status,
    create_event,
    delete_event,
    disconnect_calendar,
    find_event_conflicts,
    get_calendar_account,
    get_event,
    list_available_slots,
    list_calendars,
    list_upcoming_events,
    require_calendar_account,
    update_event,
)
from app.services.google_oauth import (
    GoogleOAuthError,
    exchange_google_token_response,
    verify_google_identity,
)
from app.services.meeting_assistant import generate_meeting_assistance
from app.services.token_encryption import encrypt_token

router = APIRouter(prefix="/integrations/calendar", tags=["Google Calendar"])
logger = logging.getLogger(__name__)
CALENDAR_STATE_COOKIE_NAME = "mailmind_calendar_oauth_state"
CALENDAR_OAUTH_PROVIDER = "calendar"
CALENDAR_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
CALENDAR_STATE_TTL_SECONDS = 600


def _delete_state_cookie(response: Response) -> None:
    response.delete_cookie(
        CALENDAR_STATE_COOKIE_NAME,
        path="/api/integrations/calendar/callback",
        secure=get_cookie_secure(),
        httponly=True,
        samesite=get_cookie_samesite(),
    )


def _calendar_redirect(*, connected: bool = False, error: str | None = None):
    target = f"{get_frontend_url()}/meetings"
    if connected:
        target += "?calendar=connected"
    elif error:
        target += f"?calendar_error={error}"
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    _delete_state_cookie(response)
    return response


def _raise_calendar_error(error: CalendarError | ConfigurationError) -> HTTPException:
    if isinstance(error, ConfigurationError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar integration is not configured",
        )
    if isinstance(error, CalendarNotConnected):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect Google Calendar before using this feature",
        )
    if isinstance(error, CalendarReauthorizationRequired):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Calendar authorization expired or is missing permissions; reconnect Calendar",
        )
    if isinstance(error, CalendarRateLimited):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Calendar rate limit reached; try again shortly",
        )
    if isinstance(error, CalendarEventNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Calendar event not found"
        )
    if isinstance(error, CalendarEventAlreadyExists):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This calendar event already exists; refresh before retrying",
        )
    if isinstance(error, CalendarWriteOutcomeUnknown):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Calendar could not confirm the event update; refresh before retrying",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Google Calendar request failed",
    )


@router.get("/status", response_model=CalendarStatusRead)
def calendar_connection_status(
    session: DatabaseSession, user: CurrentUser
) -> CalendarStatusRead:
    result = calendar_status(session, user)
    account = get_calendar_account(session, user)
    if account and account.status == "connected" and not set(CALENDAR_SCOPES).issubset(
        set(account.granted_scopes or [])
    ):
        result["requires_reconnect"] = True
    return CalendarStatusRead(**result)


@router.post("/connect", response_model=CalendarConnectRead)
def calendar_connect(
    response: Response,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> CalendarConnectRead:
    try:
        config = get_calendar_oauth_config()
        state, _, challenge = create_oauth_transaction(
            session, provider=CALENDAR_OAUTH_PROVIDER, user_id=user.id
        )
    except ConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar integration is not configured",
        ) from error

    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": f"openid email profile {CALENDAR_EVENTS_SCOPE} {CALENDAR_LIST_SCOPE}",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent select_account",
        "include_granted_scopes": "true",
    }
    response.set_cookie(
        CALENDAR_STATE_COOKIE_NAME,
        state,
        max_age=CALENDAR_STATE_TTL_SECONDS,
        path="/api/integrations/calendar/callback",
        secure=get_cookie_secure(),
        httponly=True,
        samesite=get_cookie_samesite(),
    )
    return CalendarConnectRead(
        authorization_url=f"{CALENDAR_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"
    )


@router.get("/callback")
def calendar_callback(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    state: Annotated[str | None, Query(max_length=128)] = None,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=100)] = None,
):
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state is required",
        )
    provider = session.scalar(
        select(OAuthTransaction.provider).where(
            OAuthTransaction.state_hash == token_digest(state)
        )
    )
    if provider != CALENDAR_OAUTH_PROVIDER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state validation failed",
        )
    try:
        verifier = consume_oauth_transaction(
            session,
            state,
            request.cookies.get(CALENDAR_STATE_COOKIE_NAME),
            provider=CALENDAR_OAUTH_PROVIDER,
            user_id=user.id,
            require_bound_user=True,
        )
    except OAuthStateError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state validation failed",
        ) from error

    if error:
        return _calendar_redirect(
            error="cancelled" if error == "access_denied" else "provider_error"
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth authorization code is required",
        )

    try:
        config = get_calendar_oauth_config()
        token_response = exchange_google_token_response(code, verifier, config)
        identity_token = token_response.get("id_token")
        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        expires_in = token_response.get("expires_in")
        scopes = token_response.get("scope")
        if (
            not isinstance(identity_token, str)
            or not isinstance(access_token, str)
            or not access_token
            or not isinstance(expires_in, (int, float))
            or isinstance(expires_in, bool)
            or not 1 <= expires_in <= 86400
            or not isinstance(scopes, str)
            or not set(CALENDAR_SCOPES).issubset(set(scopes.split()))
        ):
            raise GoogleOAuthError
        identity = verify_google_identity(identity_token, config.client_id)
        subject = identity.get("sub")
        email = identity.get("email")
        if (
            not isinstance(subject, str)
            or not subject
            or not isinstance(email, str)
            or identity.get("email_verified") is not True
        ):
            raise GoogleIdentityError

        account = session.scalar(
            select(ConnectedAccount).where(
                ConnectedAccount.provider == CALENDAR_PROVIDER,
                ConnectedAccount.provider_account_id == subject,
            )
        )
        if account is not None and account.user_id != user.id:
            raise GoogleIdentityError
        user_account = session.scalar(
            select(ConnectedAccount).where(
                ConnectedAccount.user_id == user.id,
                ConnectedAccount.provider == CALENDAR_PROVIDER,
            )
        )
        if user_account is not None:
            if user_account.provider_account_id != subject:
                raise GoogleIdentityError
            account = user_account
        if account is None:
            account = ConnectedAccount(
                user_id=user.id,
                provider=CALENDAR_PROVIDER,
                provider_account_id=subject,
                status="pending",
            )
            session.add(account)
            session.flush()

        if isinstance(refresh_token, str) and refresh_token:
            encrypted_refresh_token = encrypt_token(
                refresh_token, account.id, "refresh"
            )
        elif account.refresh_token_encrypted:
            encrypted_refresh_token = account.refresh_token_encrypted
        else:
            raise GoogleOAuthError
        account.email_address = email.strip().lower()[:320]
        account.access_token_encrypted = encrypt_token(
            access_token, account.id, "access"
        )
        account.refresh_token_encrypted = encrypted_refresh_token
        account.token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(expires_in)
        )
        account.granted_scopes = scopes.split()
        account.status = "connected"
        session.commit()
    except (ConfigurationError, GoogleOAuthError, GoogleIdentityError, ValueError) as exception:
        session.rollback()
        logger.warning("Calendar authorization rejected (%s)", type(exception).__name__)
        return _calendar_redirect(error="authorization_failed")
    except SQLAlchemyError as exception:
        session.rollback()
        logger.error("Calendar persistence failed (%s)", type(exception).__name__)
        return _calendar_redirect(error="authorization_failed")
    return _calendar_redirect(connected=True)


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def calendar_disconnect(
    session: DatabaseSession, user: CsrfProtectedUser
) -> Response:
    disconnect_calendar(session, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/calendars", response_model=CalendarListRead)
def calendars_list(
    session: DatabaseSession,
    user: CurrentUser,
    page_token: Annotated[str | None, Query(max_length=2000)] = None,
) -> CalendarListRead:
    try:
        account = require_calendar_account(session, user)
        result = list_calendars(build_calendar_service(account, session), page_token=page_token)
    except (CalendarError, ConfigurationError) as error:
        raise _raise_calendar_error(error) from error
    return CalendarListRead(**result)


@router.get("/events/upcoming", response_model=CalendarEventPage)
def upcoming_events(
    session: DatabaseSession,
    user: CurrentUser,
    calendar_id: Annotated[str, Query(min_length=1, max_length=255)] = "primary",
    days: Annotated[int, Query(ge=1, le=90)] = 30,
    page_token: Annotated[str | None, Query(max_length=2000)] = None,
    time_zone: Annotated[str | None, Query(max_length=100)] = None,
) -> CalendarEventPage:
    if time_zone:
        try:
            ZoneInfo(time_zone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A valid IANA time zone is required",
            ) from error
    try:
        account = require_calendar_account(session, user)
        result = list_upcoming_events(
            build_calendar_service(account, session),
            calendar_id=calendar_id,
            days=days,
            page_token=page_token,
            time_zone=time_zone,
        )
    except (CalendarError, ConfigurationError) as error:
        raise _raise_calendar_error(error) from error
    return CalendarEventPage(**result)


@router.get("/events/{event_id}", response_model=CalendarEventRead)
def event_detail(
    event_id: Annotated[str, Path(min_length=1, max_length=255)],
    session: DatabaseSession,
    user: CurrentUser,
    calendar_id: Annotated[str, Query(min_length=1, max_length=255)] = "primary",
) -> CalendarEventRead:
    try:
        account = require_calendar_account(session, user)
        event = get_event(
            build_calendar_service(account, session), calendar_id, event_id
        )
    except (CalendarError, ConfigurationError) as error:
        raise _raise_calendar_error(error) from error
    return CalendarEventRead(**event)


@router.post("/events/conflicts", response_model=CalendarConflictRead)
def event_conflicts(
    payload: CalendarConflictRequest,
    session: DatabaseSession,
    user: CsrfProtectedUser,
    calendar_id: Annotated[str, Query(min_length=1, max_length=255)] = "primary",
) -> CalendarConflictRead:
    try:
        account = require_calendar_account(session, user)
        conflicts = find_event_conflicts(
            build_calendar_service(account, session),
            calendar_id=calendar_id,
            start=payload.start,
            end=payload.end,
            time_zone=payload.time_zone,
            exclude_event_id=payload.exclude_event_id,
        )
    except (CalendarError, ConfigurationError) as error:
        raise _raise_calendar_error(error) from error
    return CalendarConflictRead(
        conflicts=[CalendarEventRead(**event) for event in conflicts],
        calendar_id=calendar_id,
    )


@router.post("/availability", response_model=CalendarAvailabilityRead)
def available_slots(
    payload: CalendarAvailabilityRequest,
    session: DatabaseSession,
    user: CsrfProtectedUser,
    calendar_id: Annotated[str, Query(min_length=1, max_length=255)] = "primary",
) -> CalendarAvailabilityRead:
    try:
        account = require_calendar_account(session, user)
        slots = list_available_slots(
            build_calendar_service(account, session),
            calendar_id=calendar_id,
            requested_date=payload.date,
            time_zone=payload.time_zone,
            duration_minutes=payload.duration_minutes,
            workday_start_hour=payload.workday_start_hour,
            workday_end_hour=payload.workday_end_hour,
        )
    except (CalendarError, ConfigurationError) as error:
        raise _raise_calendar_error(error) from error
    return CalendarAvailabilityRead(time_zone=payload.time_zone, slots=slots)


@router.post("/events", response_model=CalendarEventRead, status_code=status.HTTP_201_CREATED)
def event_create(
    payload: CalendarEventCreate,
    session: DatabaseSession,
    user: CsrfProtectedUser,
    calendar_id: Annotated[str, Query(min_length=1, max_length=255)] = "primary",
) -> CalendarEventRead:
    try:
        account = require_calendar_account(session, user)
        service = build_calendar_service(account, session)
        event = create_event(
            service,
            calendar_id,
            CalendarEventWrite.model_validate(
                payload.model_dump(exclude={"request_id", "confirm"})
            ),
            payload.request_id,
        )
    except (CalendarError, ConfigurationError) as error:
        raise _raise_calendar_error(error) from error
    return CalendarEventRead(**event)


@router.put("/events/{event_id}", response_model=CalendarEventRead)
def event_update(
    event_id: Annotated[str, Path(min_length=1, max_length=255)],
    payload: CalendarEventUpdate,
    session: DatabaseSession,
    user: CsrfProtectedUser,
    calendar_id: Annotated[str, Query(min_length=1, max_length=255)] = "primary",
) -> CalendarEventRead:
    try:
        account = require_calendar_account(session, user)
        event = update_event(
            build_calendar_service(account, session),
            calendar_id,
            event_id,
            CalendarEventWrite.model_validate(
                payload.model_dump(exclude={"confirm"})
            ),
        )
    except (CalendarError, ConfigurationError) as error:
        raise _raise_calendar_error(error) from error
    return CalendarEventRead(**event)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def event_delete(
    event_id: Annotated[str, Path(min_length=1, max_length=255)],
    payload: CalendarDeleteRequest,
    session: DatabaseSession,
    user: CsrfProtectedUser,
    calendar_id: Annotated[str, Query(min_length=1, max_length=255)] = "primary",
) -> Response:
    del payload
    try:
        account = require_calendar_account(session, user)
        delete_event(
            build_calendar_service(account, session), calendar_id, event_id
        )
    except CalendarEventNotFound:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except (CalendarError, ConfigurationError) as error:
        raise _raise_calendar_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/assistant", response_model=MeetingAssistantRead)
def meeting_assistant(
    payload: MeetingAssistantRequest,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> MeetingAssistantRead:
    try:
        return generate_meeting_assistance(session, user, payload)
    except (CalendarError, ConfigurationError) as error:
        raise _raise_calendar_error(error) from error
    except LookupError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selected Gmail message or calendar event not found",
        ) from error
    except ai_service.AIConfigurationMissing as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini is not configured",
        ) from error
    except (ai_service.AIUsageLimitExceeded, ai_service.AIProviderRateLimited) as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI usage limit reached; try again shortly",
        ) from error
    except ai_service.AIProviderTimeout as error:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Gemini did not respond in time",
        ) from error
    except ai_service.AIInputTooLarge as error:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Selected context exceeds the configured AI input limit",
        ) from error
    except (ai_service.AIInvalidOutput, ai_service.AIProviderUnavailable) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini could not provide meeting assistance",
        ) from error
