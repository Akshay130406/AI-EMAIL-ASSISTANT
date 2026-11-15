from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

import httplib2
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import TokenEncryptionConfigurationError, get_google_oauth_config
from app.models import ConnectedAccount, User
from app.schemas.calendar import CalendarEventWrite
from app.services.token_encryption import (
    TokenDecryptionError,
    decrypt_token,
    encrypt_token,
    uses_current_key,
)

logger = logging.getLogger(__name__)
CALENDAR_PROVIDER = "calendar"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
CALENDAR_SCOPES = (CALENDAR_EVENTS_SCOPE, CALENDAR_LIST_SCOPE)
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
MAX_CALENDAR_EVENTS = 250
MAX_EVENT_QUERY_PAGES = 5


class CalendarError(Exception):
    pass


class CalendarNotConnected(CalendarError):
    pass


class CalendarReauthorizationRequired(CalendarError):
    pass


class CalendarRateLimited(CalendarError):
    pass


class CalendarAPIUnavailable(CalendarError):
    pass


class CalendarAPINotEnabled(CalendarAPIUnavailable):
    pass


class CalendarWriteOutcomeUnknown(CalendarAPIUnavailable):
    pass


class CalendarEventAlreadyExists(CalendarError):
    pass


class CalendarEventNotFound(CalendarError):
    pass


class CalendarRequest(Protocol):
    def execute(self, num_retries: int = 0) -> dict[str, object]: ...


def _google_error_reasons(error: HttpError) -> set[str]:
    try:
        payload = json.loads(error.content)
    except (TypeError, ValueError):
        return set()
    details = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(details, dict):
        return set()
    reasons: set[str] = set()
    for key in ("errors", "details"):
        entries = details.get(key)
        if isinstance(entries, list):
            reasons.update(
                item["reason"]
                for item in entries
                if isinstance(item, dict) and isinstance(item.get("reason"), str)
            )
    return reasons


def get_calendar_account(session: Session, user: User) -> ConnectedAccount | None:
    return session.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.user_id == user.id,
            ConnectedAccount.provider == CALENDAR_PROVIDER,
        )
    )


def require_calendar_account(session: Session, user: User) -> ConnectedAccount:
    account = get_calendar_account(session, user)
    if account is None:
        raise CalendarNotConnected
    if (
        account.status != "connected"
        or not account.access_token_encrypted
        or not account.refresh_token_encrypted
    ):
        raise CalendarReauthorizationRequired
    if not set(CALENDAR_SCOPES).issubset(set(account.granted_scopes or [])):
        raise CalendarReauthorizationRequired
    return account


def _mark_reauthorization_required(session: Session, account: ConnectedAccount) -> None:
    account.status = "disconnected"
    account.access_token_encrypted = None
    account.refresh_token_encrypted = None
    account.token_expires_at = None
    session.commit()


def _credentials_for_account(
    session: Session, account: ConnectedAccount
) -> Credentials:
    locked = session.scalar(
        select(ConnectedAccount)
        .where(
            ConnectedAccount.id == account.id,
            ConnectedAccount.provider == CALENDAR_PROVIDER,
        )
        .with_for_update()
    )
    if locked is None or locked.status != "connected":
        raise CalendarReauthorizationRequired
    account = locked
    if not set(CALENDAR_SCOPES).issubset(set(account.granted_scopes or [])):
        raise CalendarReauthorizationRequired
    if not account.access_token_encrypted or not account.refresh_token_encrypted:
        _mark_reauthorization_required(session, account)
        raise CalendarReauthorizationRequired
    config = get_google_oauth_config()
    try:
        access_token = decrypt_token(
            account.access_token_encrypted, account.id, "access"
        )
        refresh_token = decrypt_token(
            account.refresh_token_encrypted, account.id, "refresh"
        )
    except TokenEncryptionConfigurationError as error:
        logger.error("Calendar token encryption configuration is invalid")
        raise CalendarAPIUnavailable from error
    except TokenDecryptionError as error:
        logger.error("Calendar credential decryption failed (%s)", type(error).__name__)
        raise CalendarAPIUnavailable from error

    if not uses_current_key(account.access_token_encrypted) or not uses_current_key(
        account.refresh_token_encrypted
    ):
        account.access_token_encrypted = encrypt_token(
            access_token, account.id, "access"
        )
        account.refresh_token_encrypted = encrypt_token(
            refresh_token, account.id, "refresh"
        )
        session.commit()

    expiry = account.token_expires_at
    if expiry is not None and expiry.tzinfo is not None:
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=config.client_id,
        client_secret=config.client_secret,
        scopes=list(CALENDAR_SCOPES),
        expiry=expiry,
    )
    if not credentials.valid:
        try:
            credentials.refresh(GoogleRequest())
        except RefreshError as error:
            _mark_reauthorization_required(session, account)
            logger.warning("Calendar token refresh rejected (%s)", type(error).__name__)
            raise CalendarReauthorizationRequired from error
        except (GoogleAuthError, httplib2.HttpLib2Error, OSError, ValueError) as error:
            logger.warning("Calendar token refresh failed (%s)", type(error).__name__)
            raise CalendarAPIUnavailable from error
        account.access_token_encrypted = encrypt_token(
            credentials.token, account.id, "access"
        )
        if credentials.refresh_token:
            account.refresh_token_encrypted = encrypt_token(
                credentials.refresh_token, account.id, "refresh"
            )
        expiry = credentials.expiry
        if expiry is not None:
            expiry = (
                expiry.replace(tzinfo=timezone.utc)
                if expiry.tzinfo is None
                else expiry.astimezone(timezone.utc)
            )
        account.token_expires_at = expiry
        session.commit()
    return credentials


def build_calendar_service(account: ConnectedAccount, session: Session) -> Resource:
    credentials = _credentials_for_account(session, account)
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _execute(request: CalendarRequest) -> dict[str, object]:
    try:
        result = request.execute(num_retries=2)
    except HttpError as error:
        response = getattr(error, "resp", None)
        code = getattr(response, "status", None)
        if code == 401:
            raise CalendarReauthorizationRequired from error
        if code == 404:
            raise CalendarEventNotFound from error
        if code == 429:
            raise CalendarRateLimited from error
        reasons = _google_error_reasons(error)
        if reasons.intersection({"accessNotConfigured"}):
            raise CalendarAPINotEnabled from error
        if reasons.intersection({"authError", "insufficientPermissions"}):
            raise CalendarReauthorizationRequired from error
        if reasons.intersection({"rateLimitExceeded", "userRateLimitExceeded"}):
            raise CalendarRateLimited from error
        raise CalendarAPIUnavailable from error
    except (GoogleAuthError, httplib2.HttpLib2Error, OSError, ValueError) as error:
        logger.warning("Calendar API request failed (%s)", type(error).__name__)
        raise CalendarAPIUnavailable from error
    if not isinstance(result, dict):
        raise CalendarAPIUnavailable
    return result


def _execute_write(request: CalendarRequest) -> dict[str, object] | None:
    try:
        result = request.execute()
    except HttpError as error:
        response = getattr(error, "resp", None)
        code = getattr(response, "status", None)
        if code == 401:
            raise CalendarReauthorizationRequired from error
        if code == 429:
            raise CalendarRateLimited from error
        if code == 409:
            raise CalendarEventAlreadyExists from error
        if code == 404:
            raise CalendarEventNotFound from error
        reasons = _google_error_reasons(error)
        if reasons.intersection({"accessNotConfigured"}):
            raise CalendarAPINotEnabled from error
        if reasons.intersection({"authError", "insufficientPermissions"}):
            raise CalendarReauthorizationRequired from error
        if reasons.intersection({"rateLimitExceeded", "userRateLimitExceeded"}):
            raise CalendarRateLimited from error
        logger.warning("Calendar write outcome is uncertain (HTTP %s)", code)
        raise CalendarWriteOutcomeUnknown from error
    except (GoogleAuthError, httplib2.HttpLib2Error, OSError, ValueError) as error:
        logger.warning("Calendar write outcome is uncertain (%s)", type(error).__name__)
        raise CalendarWriteOutcomeUnknown from error
    if result is None:
        return None
    if not isinstance(result, dict):
        raise CalendarWriteOutcomeUnknown
    return result


def _calendar_item(item: dict[str, object]) -> dict[str, object]:
    calendar_id = item.get("id")
    if not isinstance(calendar_id, str) or not calendar_id:
        raise CalendarAPIUnavailable
    return {
        "id": calendar_id,
        "summary": str(item.get("summary") or calendar_id)[:500],
        "time_zone": item.get("timeZone")
        if isinstance(item.get("timeZone"), str)
        else None,
        "primary": item.get("primary") is True,
        "access_role": item.get("accessRole")
        if isinstance(item.get("accessRole"), str)
        else None,
    }


def list_calendars(
    service: Resource, *, page_token: str | None = None
) -> dict[str, object]:
    response = _execute(
        service.calendarList().list(
            maxResults=100,
            pageToken=page_token,
            showDeleted=False,
            showHidden=False,
        )
    )
    items = response.get("items")
    calendars = [
        _calendar_item(item)
        for item in items[:100]
        if isinstance(item, dict)
    ] if isinstance(items, list) else []
    next_page_token = response.get("nextPageToken")
    return {
        "items": calendars,
        "next_page_token": next_page_token
        if isinstance(next_page_token, str)
        else None,
    }


def _event_item(item: dict[str, object], calendar_id: str) -> dict[str, object]:
    event_id = item.get("id")
    start = item.get("start")
    end = item.get("end")
    if (
        not isinstance(event_id, str)
        or not isinstance(start, dict)
        or not isinstance(end, dict)
    ):
        raise CalendarAPIUnavailable
    start_value = start.get("dateTime") or start.get("date")
    end_value = end.get("dateTime") or end.get("date")
    attendees = item.get("attendees")
    return {
        "id": event_id,
        "calendar_id": calendar_id,
        "summary": str(item.get("summary") or "(no title)")[:250],
        "description": str(item.get("description") or "")[:10000],
        "start": start_value if isinstance(start_value, str) else "",
        "end": end_value if isinstance(end_value, str) else "",
        "time_zone": start.get("timeZone")
        if isinstance(start.get("timeZone"), str)
        else None,
        "attendees": [
            attendee["email"]
            for attendee in attendees
            if isinstance(attendee, dict)
            and isinstance(attendee.get("email"), str)
        ][:100]
        if isinstance(attendees, list)
        else [],
        "html_link": item.get("htmlLink")
        if isinstance(item.get("htmlLink"), str)
        else None,
        "status": item.get("status")
        if isinstance(item.get("status"), str)
        else None,
    }


def list_upcoming_events(
    service: Resource,
    *,
    calendar_id: str,
    days: int = 30,
    page_token: str | None = None,
    time_zone: str | None = None,
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    response = _execute(
        service.events().list(
            calendarId=calendar_id,
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=days)).isoformat(),
            maxResults=MAX_CALENDAR_EVENTS,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
            timeZone=time_zone,
        )
    )
    items = response.get("items")
    events = [
        _event_item(item, calendar_id)
        for item in items[:MAX_CALENDAR_EVENTS]
        if isinstance(item, dict) and item.get("status") != "cancelled"
    ] if isinstance(items, list) else []
    token = response.get("nextPageToken")
    return {
        "items": events,
        "next_page_token": token if isinstance(token, str) else None,
    }


def get_event(service: Resource, calendar_id: str, event_id: str) -> dict[str, object]:
    event = _execute(
        service.events().get(calendarId=calendar_id, eventId=event_id)
    )
    return _event_item(event, calendar_id)


def _list_event_pages(service: Resource, **parameters: object) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    page_token: str | None = None
    for _ in range(MAX_EVENT_QUERY_PAGES):
        response = _execute(
            service.events().list(
                **parameters,
                pageToken=page_token,
                maxResults=MAX_CALENDAR_EVENTS,
            )
        )
        page = response.get("items")
        if isinstance(page, list):
            items.extend(item for item in page if isinstance(item, dict))
        page_token = response.get("nextPageToken")
        if not isinstance(page_token, str) or not page_token:
            return items
    raise CalendarAPIUnavailable


def _event_body(payload: CalendarEventWrite) -> dict[str, object]:
    zone = ZoneInfo(payload.time_zone)
    return {
        "summary": payload.summary,
        "description": payload.description,
        "start": {
            "dateTime": payload.start.astimezone(zone).isoformat(),
            "timeZone": payload.time_zone,
        },
        "end": {
            "dateTime": payload.end.astimezone(zone).isoformat(),
            "timeZone": payload.time_zone,
        },
        "attendees": [{"email": email} for email in payload.attendees],
    }


def _same_event_instant(left: object, right: object) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    try:
        return datetime.fromisoformat(left.replace("Z", "+00:00")) == datetime.fromisoformat(
            right.replace("Z", "+00:00")
        )
    except ValueError:
        return False


def _normalized_attendees(value: object) -> set[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return {item.casefold() for item in value}


def create_event(
    service: Resource,
    calendar_id: str,
    payload: CalendarEventWrite,
    request_id: UUID,
) -> dict[str, object]:
    # Google event IDs are restricted to lowercase base32hex characters.
    event_id = request_id.hex
    body = _event_body(payload)
    body["id"] = event_id
    try:
        created = _execute_write(
            service.events().insert(calendarId=calendar_id, body=body, sendUpdates="all")
        )
    except CalendarEventAlreadyExists:
        existing = get_event(service, calendar_id, event_id)
        start = body.get("start")
        end = body.get("end")
        expected_start = start.get("dateTime") if isinstance(start, dict) else None
        expected_end = end.get("dateTime") if isinstance(end, dict) else None
        if (
            existing["summary"] == payload.summary
            and existing["description"] == payload.description
            and _same_event_instant(existing["start"], expected_start)
            and _same_event_instant(existing["end"], expected_end)
            and _normalized_attendees(existing["attendees"])
            == _normalized_attendees(payload.attendees)
        ):
            return existing
        raise
    if created is None:
        raise CalendarWriteOutcomeUnknown
    return _event_item(created, calendar_id)


def update_event(
    service: Resource,
    calendar_id: str,
    event_id: str,
    payload: CalendarEventWrite,
) -> dict[str, object]:
    updated = _execute_write(
        service.events().patch(
            calendarId=calendar_id,
            eventId=event_id,
            body=_event_body(payload),
            sendUpdates="all",
        )
    )
    if updated is None:
        raise CalendarWriteOutcomeUnknown
    return _event_item(updated, calendar_id)


def delete_event(service: Resource, calendar_id: str, event_id: str) -> None:
    _execute_write(
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id,
            sendUpdates="all",
        )
    )


def find_event_conflicts(
    service: Resource,
    *,
    calendar_id: str,
    start: datetime,
    end: datetime,
    time_zone: str,
    exclude_event_id: str | None = None,
) -> list[dict[str, object]]:
    items = _list_event_pages(
        service,
        calendarId=calendar_id,
        timeMin=start.astimezone(timezone.utc).isoformat(),
        timeMax=end.astimezone(timezone.utc).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        timeZone=time_zone,
    )
    conflicts: list[dict[str, object]] = []
    for item in items:
        if item.get("id") == exclude_event_id or not _event_blocks_time(item):
            continue
        interval = _event_interval(item, ZoneInfo(time_zone))
        if interval is None:
            continue
        existing_start, existing_end = interval
        if existing_start < end and existing_end > start:
            conflicts.append(_event_item(item, calendar_id))
    return conflicts


def _event_interval(
    event: dict[str, object], fallback_zone: ZoneInfo
) -> tuple[datetime, datetime] | None:
    start = event.get("start")
    end = event.get("end")
    if not isinstance(start, dict) or not isinstance(end, dict):
        return None
    start_date_time = start.get("dateTime")
    end_date_time = end.get("dateTime")
    try:
        if isinstance(start_date_time, str) and isinstance(end_date_time, str):
            starts = datetime.fromisoformat(start_date_time.replace("Z", "+00:00"))
            ends = datetime.fromisoformat(end_date_time.replace("Z", "+00:00"))
            return starts, ends
        start_date = start.get("date")
        end_date = end.get("date")
        if isinstance(start_date, str) and isinstance(end_date, str):
            starts = datetime.combine(date.fromisoformat(start_date), time.min, fallback_zone)
            ends = datetime.combine(date.fromisoformat(end_date), time.min, fallback_zone)
            return starts, ends
    except ValueError:
        return None
    return None


def _event_blocks_time(event: dict[str, object]) -> bool:
    if event.get("status") == "cancelled" or event.get("transparency") == "transparent":
        return False
    attendees = event.get("attendees")
    if isinstance(attendees, list) and any(
        isinstance(attendee, dict)
        and attendee.get("self") is True
        and attendee.get("responseStatus") == "declined"
        for attendee in attendees
    ):
        return False
    return True


def list_available_slots(
    service: Resource,
    *,
    calendar_id: str,
    requested_date: date,
    time_zone: str,
    duration_minutes: int,
    workday_start_hour: int,
    workday_end_hour: int,
) -> list[dict[str, object]]:
    zone = ZoneInfo(time_zone)
    window_start = datetime.combine(
        requested_date, time(hour=workday_start_hour), zone
    )
    window_end = datetime.combine(
        requested_date, time.min, zone
    ) + timedelta(hours=workday_end_hour)
    items = _list_event_pages(
        service,
        calendarId=calendar_id,
        timeMin=window_start.astimezone(timezone.utc).isoformat(),
        timeMax=window_end.astimezone(timezone.utc).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        timeZone=time_zone,
    )
    busy_intervals = [
        interval
        for item in items
        if _event_blocks_time(item)
        for interval in [_event_interval(item, zone)]
        if interval is not None
    ]
    duration = timedelta(minutes=duration_minutes)
    slots: list[dict[str, object]] = []
    candidate = window_start
    while candidate + duration <= window_end and len(slots) < 20:
        candidate_end = candidate + duration
        is_busy = any(
            busy_start < candidate_end and busy_end > candidate
            for busy_start, busy_end in busy_intervals
        )
        if not is_busy:
            slots.append(
                {
                    "start": candidate,
                    "end": candidate_end,
                    "time_zone": time_zone,
                    "calendar_free": True,
                }
            )
        candidate += timedelta(minutes=15)
    return slots


def disconnect_calendar(session: Session, user: User) -> None:
    account = session.scalar(
        select(ConnectedAccount)
        .where(
            ConnectedAccount.user_id == user.id,
            ConnectedAccount.provider == CALENDAR_PROVIDER,
        )
        .with_for_update()
    )
    if account is None:
        return
    account.status = "disconnected"
    account.access_token_encrypted = None
    account.refresh_token_encrypted = None
    account.token_expires_at = None
    session.commit()


def calendar_status(session: Session, user: User) -> dict[str, object]:
    account = get_calendar_account(session, user)
    if account is None:
        return {
            "connected": False,
            "status": "not_connected",
            "email": None,
            "requires_reconnect": False,
        }
    active = (
        account.status == "connected"
        and bool(account.access_token_encrypted)
        and bool(account.refresh_token_encrypted)
        and set(CALENDAR_SCOPES).issubset(set(account.granted_scopes or []))
    )
    return {
        "connected": active,
        "status": "connected" if active else "disconnected",
        "email": account.email_address,
        "requires_reconnect": not active,
    }
