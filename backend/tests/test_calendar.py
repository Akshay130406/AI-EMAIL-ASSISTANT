import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import httplib2
from googleapiclient.errors import HttpError
from sqlalchemy import select
from google.auth.exceptions import RefreshError

from app.api.routes.calendar import CALENDAR_STATE_COOKIE_NAME
from app.models import ConnectedAccount, Email, OAuthTransaction, User
from app.schemas.calendar import (
    CalendarEventWrite,
    MeetingAssistantRead,
    MeetingAssistantRequest,
)
from app.services import calendar as calendar_service
from app.core.config import GoogleOAuthConfig
from app.services.meeting_assistant import generate_meeting_assistance
from app.services.token_encryption import decrypt_token, encrypt_token
from tests.helpers import get_development_user


def _configure_calendar(monkeypatch):
    key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback"
    )
    monkeypatch.setenv(
        "CALENDAR_REDIRECT_URI",
        "http://localhost:8000/api/integrations/calendar/callback",
    )
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY_ID", "test-key")


def _start_calendar_auth(client):
    response = client.post("/api/integrations/calendar/connect")
    assert response.status_code == 200
    params = parse_qs(urlparse(response.json()["authorization_url"]).query)
    return response, params


def _mock_calendar_identity(monkeypatch, *, subject="calendar-subject"):
    from app.api.routes import calendar as routes

    monkeypatch.setattr(
        routes,
        "exchange_google_token_response",
        lambda code, verifier, config: {
            "id_token": "mock-id-token",
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "scope": (
                "openid email profile "
                f"{calendar_service.CALENDAR_EVENTS_SCOPE} "
                f"{calendar_service.CALENDAR_LIST_SCOPE}"
            ),
        },
    )
    monkeypatch.setattr(
        routes,
        "verify_google_identity",
        lambda token, client_id: {
            "sub": subject,
            "email": "calendar@example.test",
            "email_verified": True,
        },
    )


def test_calendar_oauth_requests_narrow_scopes_and_pkce(
    client, monkeypatch
):
    _configure_calendar(monkeypatch)
    response, params = _start_calendar_auth(client)

    scopes = params["scope"][0].split()
    assert scopes == [
        "openid",
        "email",
        "profile",
        calendar_service.CALENDAR_EVENTS_SCOPE,
        calendar_service.CALENDAR_LIST_SCOPE,
    ]
    assert params["code_challenge_method"] == ["S256"]
    assert params["access_type"] == ["offline"]
    assert params["state"][0] == response.cookies[CALENDAR_STATE_COOKIE_NAME]


def test_calendar_oauth_callback_validates_state_and_provider_errors(
    client, db_session_factory, monkeypatch
):
    _configure_calendar(monkeypatch)
    from app.api.routes import calendar as routes

    _, params = _start_calendar_auth(client)
    state = params["state"][0]
    invalid = client.get(
        "/api/integrations/calendar/callback",
        params={"state": "not-the-state", "code": "mock-code"},
        cookies={CALENDAR_STATE_COOKIE_NAME: state},
    )
    assert invalid.status_code == 400
    with db_session_factory() as session:
        assert session.scalar(select(OAuthTransaction)) is not None

    exchange = []
    monkeypatch.setattr(
        routes,
        "exchange_google_token_response",
        lambda *args: exchange.append(args),
    )
    cancelled = client.get(
        "/api/integrations/calendar/callback",
        params={"state": state, "error": "access_denied"},
        cookies={CALENDAR_STATE_COOKIE_NAME: state},
    )
    assert cancelled.status_code == 303
    assert "calendar_error=cancelled" in cancelled.headers["location"]
    assert exchange == []

    missing_code_start, missing_code_params = _start_calendar_auth(client)
    missing_state = missing_code_params["state"][0]
    missing_code = client.get(
        "/api/integrations/calendar/callback",
        params={"state": missing_state},
        cookies={CALENDAR_STATE_COOKIE_NAME: missing_state},
    )
    assert missing_code.status_code == 400
    assert missing_code_start.status_code == 200


def test_calendar_oauth_persists_only_encrypted_tokens_and_reuses_refresh_token(
    client, db_session_factory, monkeypatch
):
    _configure_calendar(monkeypatch)
    _mock_calendar_identity(monkeypatch)
    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        account = ConnectedAccount(
            user_id=user.id,
            provider="calendar",
            provider_account_id="calendar-subject",
            email_address="calendar@example.test",
            status="connected",
            granted_scopes=[
                calendar_service.CALENDAR_EVENTS_SCOPE,
                calendar_service.CALENDAR_LIST_SCOPE,
            ],
        )
        session.add(account)
        session.flush()
        account.refresh_token_encrypted = encrypt_token(
            "old-refresh", account.id, "refresh"
        )
        session.commit()
        account_id = account.id

    from app.api.routes import calendar as routes

    original_exchange = routes.exchange_google_token_response

    def no_refresh_token(code, verifier, config):
        response = original_exchange(code, verifier, config)
        response.pop("refresh_token")
        return response

    monkeypatch.setattr(routes, "exchange_google_token_response", no_refresh_token)
    _, params = _start_calendar_auth(client)
    state = params["state"][0]
    response = client.get(
        "/api/integrations/calendar/callback",
        params={"state": state, "code": "mock-code"},
        cookies={CALENDAR_STATE_COOKIE_NAME: state},
    )
    assert response.status_code == 303
    assert "calendar=connected" in response.headers["location"]

    with db_session_factory() as session:
        account = session.get(ConnectedAccount, account_id)
        assert account is not None
        assert account.status == "connected"
        assert decrypt_token(account.access_token_encrypted, account.id, "access") == "new-access"
        assert decrypt_token(account.refresh_token_encrypted, account.id, "refresh") == "old-refresh"
        assert "new-access" not in account.access_token_encrypted
        assert "old-refresh" not in account.refresh_token_encrypted


def test_calendar_endpoints_require_authentication(unauthenticated_client):
    assert unauthenticated_client.get("/api/integrations/calendar/status").status_code == 401
    assert unauthenticated_client.get(
        "/api/integrations/calendar/events/upcoming"
    ).status_code == 401
    assert unauthenticated_client.post(
        "/api/integrations/calendar/assistant",
        json={"operation": "summary", "event_id": "event-1"},
    ).status_code == 401


def test_meeting_assistant_rejects_foreign_email_context(
    client, db_session_factory, monkeypatch
):
    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        foreign = User(email="foreign-calendar@example.test")
        session.add(foreign)
        session.flush()
        message = Email(
            user_id=foreign.id,
            source="gmail",
            external_message_id="foreign-message",
            sender="Sender <sender@example.test>",
            recipients=[],
            subject="Private meeting",
            body="Private details",
        )
        session.add(message)
        session.commit()
        email_id = message.id

    from app.services import ai

    calls = []
    monkeypatch.setattr(
        ai,
        "_generate",
        lambda *args, **kwargs: calls.append(args),
    )
    with db_session_factory() as session:
        current_user = session.get(User, user.id)
        with pytest.raises(LookupError):
            generate_meeting_assistance(
                session,
                current_user,
                MeetingAssistantRequest(
                    operation="agenda",
                    email_ids=[email_id],
                ),
            )
    assert calls == []


def test_meeting_assistant_filters_attendees_and_never_confirms_availability(
    client, db_session_factory, monkeypatch
):
    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        message = Email(
            user_id=user.id,
            source="gmail",
            external_message_id="owned-message",
            sender="sender@example.test",
            recipients=["reader@example.test"],
            subject="Meeting",
            body="Please meet Thursday.",
        )
        session.add(message)
        session.commit()
        email_id = message.id

    from app.services import ai

    monkeypatch.setattr(
        ai,
        "_generate",
        lambda *args, **kwargs: MeetingAssistantRead(
            title="Meeting",
            summary="The email proposes a meeting.",
            attendees=["sender@example.test", "invented@example.test"],
            suggested_times=["Thursday"],
            calendar_availability_confirmed=True,
        ),
    )
    with db_session_factory() as session:
        current_user = session.get(User, user.id)
        result = generate_meeting_assistance(
            session,
            current_user,
            MeetingAssistantRequest(operation="agenda", email_ids=[email_id]),
        )
    assert result.source_email_ids == [email_id]
    assert result.attendees == ["sender@example.test"]
    assert result.calendar_availability_confirmed is False


def test_meeting_assistant_fetches_event_from_requested_calendar(
    client, db_session_factory, monkeypatch
):
    from app.services import meeting_assistant
    from app.services import ai

    user = get_development_user(db_session_factory)
    calls = []
    event = {
        "id": "shared-event",
        "calendar_id": "team-calendar",
        "summary": "Team planning",
        "description": "Review quarterly goals.",
        "start": "2030-01-02T10:00:00-08:00",
        "end": "2030-01-02T10:30:00-08:00",
        "time_zone": "America/Los_Angeles",
        "attendees": [],
        "html_link": None,
        "status": "confirmed",
    }
    monkeypatch.setattr(meeting_assistant, "require_calendar_account", lambda session, owner: object())
    monkeypatch.setattr(meeting_assistant, "build_calendar_service", lambda account, session: object())
    monkeypatch.setattr(
        meeting_assistant,
        "get_event",
        lambda service, calendar_id, event_id: calls.append((calendar_id, event_id)) or event,
    )
    monkeypatch.setattr(
        ai,
        "_generate",
        lambda *args, **kwargs: MeetingAssistantRead(summary="Preparation notes"),
    )
    with db_session_factory() as session:
        current_user = session.get(User, user.id)
        result = generate_meeting_assistance(
            session,
            current_user,
            MeetingAssistantRequest(
                operation="agenda",
                event_id="shared-event",
                calendar_id="team-calendar",
            ),
        )
    assert calls == [("team-calendar", "shared-event")]
    assert result.summary == "Preparation notes"
    assert result.calendar_availability_confirmed is False


def test_calendar_availability_excludes_busy_time_and_does_not_claim_invitee_availability():
    class Request:
        def execute(self, num_retries=0):
            return {
                "items": [
                    {
                        "id": "busy",
                        "start": {"dateTime": "2025-01-02T10:00:00-08:00"},
                        "end": {"dateTime": "2025-01-02T11:00:00-08:00"},
                    }
                ]
            }

    class Events:
        def list(self, **kwargs):
            return Request()

    class Service:
        def events(self):
            return Events()

    slots = calendar_service.list_available_slots(
        Service(),
        calendar_id="primary",
        requested_date=datetime(2025, 1, 2).date(),
        time_zone="America/Los_Angeles",
        duration_minutes=60,
        workday_start_hour=9,
        workday_end_hour=12,
    )
    assert slots
    assert all(
        not (
            slot["start"] < datetime(2025, 1, 2, 11, tzinfo=ZoneInfo("America/Los_Angeles"))
            and slot["end"] > datetime(2025, 1, 2, 10, tzinfo=ZoneInfo("America/Los_Angeles"))
        )
        for slot in slots
    )


def test_calendar_refresh_rotates_tokens_and_revocation_requires_reauthorization(
    client, db_session_factory, monkeypatch
):
    _configure_calendar(monkeypatch)
    monkeypatch.setattr(
        calendar_service,
        "get_google_oauth_config",
        lambda: GoogleOAuthConfig(
            client_id="client",
            client_secret="secret",
            redirect_uri="http://localhost/callback",
        ),
    )
    user = get_development_user(db_session_factory)

    class RotatingCredentials:
        def __init__(self, **kwargs):
            self.token = kwargs["token"]
            self.refresh_token = kwargs["refresh_token"]
            self.expiry = kwargs["expiry"]
            self.valid = False

        def refresh(self, request):
            self.token = "rotated-access"
            self.refresh_token = "rotated-refresh"
            self.expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    monkeypatch.setattr(calendar_service, "Credentials", RotatingCredentials)
    with db_session_factory() as session:
        account = ConnectedAccount(
            user_id=user.id,
            provider="calendar",
            provider_account_id="calendar-refresh-subject",
            status="connected",
            granted_scopes=list(calendar_service.CALENDAR_SCOPES),
            token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        session.add(account)
        session.flush()
        account.access_token_encrypted = encrypt_token("expired", account.id, "access")
        account.refresh_token_encrypted = encrypt_token("refresh", account.id, "refresh")
        session.commit()

        credentials = calendar_service._credentials_for_account(session, account)

        assert credentials.token == "rotated-access"
        assert credentials.refresh_token == "rotated-refresh"
        assert decrypt_token(account.access_token_encrypted, account.id, "access") == "rotated-access"
        assert decrypt_token(account.refresh_token_encrypted, account.id, "refresh") == "rotated-refresh"

        class RevokedCredentials(RotatingCredentials):
            def refresh(self, request):
                raise RefreshError("revoked")

        monkeypatch.setattr(calendar_service, "Credentials", RevokedCredentials)
        account.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        session.commit()
        with pytest.raises(calendar_service.CalendarReauthorizationRequired):
            calendar_service._credentials_for_account(session, account)
        assert account.status == "disconnected"
        assert account.access_token_encrypted is None
        assert account.refresh_token_encrypted is None


def test_calendar_event_create_uses_deterministic_id_and_never_retries_writes():
    request_id = uuid4()
    request_calls = []
    captured = {}

    class Request:
        def execute(self, num_retries=0):
            request_calls.append(num_retries)
            return {
                "id": captured["body"]["id"],
                "summary": captured["body"]["summary"],
                "start": captured["body"]["start"],
                "end": captured["body"]["end"],
                "attendees": captured["body"]["attendees"],
            }

    class Events:
        def insert(self, **kwargs):
            captured.update(kwargs)
            return Request()

    class Service:
        def events(self):
            return Events()

    payload = CalendarEventWrite(
        summary="Planning",
        description="",
        start=datetime(2030, 1, 2, 10, tzinfo=ZoneInfo("UTC")),
        end=datetime(2030, 1, 2, 10, 30, tzinfo=ZoneInfo("UTC")),
        time_zone="UTC",
        attendees=["person@example.test"],
    )
    event = calendar_service.create_event(
        Service(),
        "primary",
        payload,
        request_id,
    )
    assert captured["body"]["id"] == request_id.hex
    assert captured["sendUpdates"] == "all"
    assert event["summary"] == "Planning"
    assert request_calls == [0]


def test_calendar_event_update_delete_and_timezone_payloads():
    calls = []

    class Request:
        def __init__(self, result):
            self.result = result

        def execute(self):
            return self.result

    class Events:
        def patch(self, **kwargs):
            calls.append(("patch", kwargs))
            return Request({
                "id": kwargs["eventId"],
                "summary": kwargs["body"]["summary"],
                "start": kwargs["body"]["start"],
                "end": kwargs["body"]["end"],
                "attendees": kwargs["body"]["attendees"],
            })

        def delete(self, **kwargs):
            calls.append(("delete", kwargs))
            return Request(None)

    class Service:
        def events(self):
            return Events()

    payload = CalendarEventWrite(
        summary="Updated meeting",
        description="Review",
        start=datetime(2030, 6, 1, 17, tzinfo=timezone.utc),
        end=datetime(2030, 6, 1, 17, 30, tzinfo=timezone.utc),
        time_zone="America/Los_Angeles",
        attendees=["guest@example.test"],
    )
    updated = calendar_service.update_event(
        Service(), "team-calendar", "event-2", payload
    )
    calendar_service.delete_event(Service(), "team-calendar", "event-2")

    assert updated["start"] == "2030-06-01T10:00:00-07:00"
    assert calls[0][1]["calendarId"] == "team-calendar"
    assert calls[0][1]["body"]["start"]["timeZone"] == "America/Los_Angeles"
    assert calls[0][1]["sendUpdates"] == "all"
    assert calls[1][1]["calendarId"] == "team-calendar"
    assert calls[1][1]["sendUpdates"] == "all"


def test_calendar_write_ambiguous_failure_is_not_retried():
    class FailedRequest:
        calls = 0

        def execute(self, num_retries=0):
            self.calls += 1
            raise HttpError(
                httplib2.Response({"status": "503"}),
                b"provider details are private",
            )

    request = FailedRequest()
    with pytest.raises(calendar_service.CalendarWriteOutcomeUnknown):
        calendar_service._execute_write(request)
    assert request.calls == 1


def test_calendar_write_permission_errors_require_reauthorization():
    class FailedRequest:
        def execute(self):
            raise HttpError(
                httplib2.Response({"status": "403"}),
                b'{"error":{"errors":[{"reason":"insufficientPermissions"}]}}',
            )

    with pytest.raises(calendar_service.CalendarReauthorizationRequired):
        calendar_service._execute_write(FailedRequest())


@pytest.mark.parametrize(
    ("reason", "error_type"),
    [
        ("insufficientPermissions", calendar_service.CalendarReauthorizationRequired),
        ("userRateLimitExceeded", calendar_service.CalendarRateLimited),
    ],
)
def test_calendar_read_permission_and_rate_limit_errors_are_classified(
    reason, error_type
):
    class FailedRequest:
        def execute(self, num_retries=0):
            raise HttpError(
                httplib2.Response({"status": "403"}),
                f'{{"error":{{"errors":[{{"reason":"{reason}"}}]}}}}'.encode(),
            )

    with pytest.raises(error_type):
        calendar_service._execute(FailedRequest())


def test_calendar_read_endpoints_list_calendars_events_and_details(
    client, monkeypatch
):
    from app.api.routes import calendar as routes

    calls = []
    monkeypatch.setattr(routes, "require_calendar_account", lambda session, user: object())
    monkeypatch.setattr(routes, "build_calendar_service", lambda account, session: object())
    monkeypatch.setattr(
        routes,
        "list_calendars",
        lambda service, page_token=None: {
            "items": [{
                "id": "team-calendar",
                "summary": "Team",
                "time_zone": "America/Los_Angeles",
                "primary": False,
                "access_role": "reader",
            }],
            "next_page_token": "next",
        },
    )
    event = {
        "id": "event-1",
        "calendar_id": "team-calendar",
        "summary": "Planning",
        "description": "Agenda",
        "start": "2030-01-02T10:00:00-08:00",
        "end": "2030-01-02T10:30:00-08:00",
        "time_zone": "America/Los_Angeles",
        "attendees": [],
        "html_link": None,
        "status": "confirmed",
    }

    def list_events(service, **kwargs):
        calls.append(("list", kwargs))
        return {"items": [event], "next_page_token": None}

    def get_event(service, calendar_id, event_id):
        calls.append(("get", calendar_id, event_id))
        return event

    monkeypatch.setattr(routes, "list_upcoming_events", list_events)
    monkeypatch.setattr(routes, "get_event", get_event)

    calendars = client.get("/api/integrations/calendar/calendars")
    assert calendars.status_code == 200
    assert calendars.json()["items"][0]["id"] == "team-calendar"
    assert calendars.json()["items"][0]["access_role"] == "reader"
    assert calendars.json()["next_page_token"] == "next"

    upcoming = client.get(
        "/api/integrations/calendar/events/upcoming",
        params={"calendar_id": "team-calendar", "time_zone": "America/Los_Angeles"},
    )
    assert upcoming.status_code == 200
    assert upcoming.json()["items"][0]["summary"] == "Planning"
    assert calls[0][1]["calendar_id"] == "team-calendar"
    assert calls[0][1]["time_zone"] == "America/Los_Angeles"

    detail = client.get(
        "/api/integrations/calendar/events/event-1",
        params={"calendar_id": "team-calendar"},
    )
    assert detail.status_code == 200
    assert detail.json()["time_zone"] == "America/Los_Angeles"
    assert calls[-1] == ("get", "team-calendar", "event-1")


def test_calendar_conflict_and_availability_routes_are_scoped_and_csrf_protected(
    client, monkeypatch
):
    from app.api.routes import calendar as routes

    calls = []
    monkeypatch.setattr(routes, "require_calendar_account", lambda session, user: object())
    monkeypatch.setattr(routes, "build_calendar_service", lambda account, session: object())
    monkeypatch.setattr(
        routes,
        "find_event_conflicts",
        lambda service, **kwargs: calls.append(("conflicts", kwargs)) or [],
    )
    monkeypatch.setattr(
        routes,
        "list_available_slots",
        lambda service, **kwargs: calls.append(("availability", kwargs)) or [],
    )
    request_payload = {
        "start": "2030-01-02T10:00:00Z",
        "end": "2030-01-02T10:30:00Z",
        "time_zone": "UTC",
    }
    no_csrf_client = client
    csrf_token = client.csrf_token
    no_csrf_client.set_session(client.session_token, None)
    rejected = no_csrf_client.post(
        "/api/integrations/calendar/events/conflicts",
        params={"calendar_id": "team"},
        json=request_payload,
    )
    assert rejected.status_code == 403
    assert calls == []

    no_csrf_client.set_session(client.session_token, csrf_token)
    conflicts = client.post(
        "/api/integrations/calendar/events/conflicts",
        params={"calendar_id": "team"},
        json=request_payload,
    )
    availability = client.post(
        "/api/integrations/calendar/availability",
        params={"calendar_id": "team"},
        json={
            "date": "2030-01-02",
            "time_zone": "America/Los_Angeles",
            "duration_minutes": 30,
        },
    )
    assert conflicts.status_code == 200
    assert availability.status_code == 200
    assert calls[0][1]["calendar_id"] == "team"
    assert calls[1][1]["calendar_id"] == "team"
    assert calls[1][1]["time_zone"] == "America/Los_Angeles"
    assert availability.json()["availability_scope"] == "connected_user_calendar_only"


def test_calendar_account_and_disconnect_are_user_scoped(
    client, db_session_factory, monkeypatch
):
    _configure_calendar(monkeypatch)
    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        foreign = User(email="foreign-calendar-owner@example.test")
        session.add(foreign)
        session.flush()
        foreign_account = ConnectedAccount(
            user_id=foreign.id,
            provider="calendar",
            provider_account_id="foreign-subject",
            status="connected",
            granted_scopes=list(calendar_service.CALENDAR_SCOPES),
        )
        session.add(foreign_account)
        session.commit()
        foreign_account_id = foreign_account.id

    before = client.get("/api/integrations/calendar/status")
    assert before.status_code == 200
    assert before.json()["connected"] is False
    assert client.get("/api/integrations/calendar/calendars").status_code == 409

    disconnected = client.delete("/api/integrations/calendar/disconnect")
    assert disconnected.status_code == 204
    with db_session_factory() as session:
        account = session.get(ConnectedAccount, foreign_account_id)
        assert account is not None
        assert account.status == "connected"
    assert client.get("/api/integrations/calendar/status").json()["connected"] is False


def test_calendar_event_api_requires_confirmed_user_scoped_writes(
    client, monkeypatch
):
    from app.api.routes import calendar as routes

    calls = []
    event_data = {
        "id": "event-1",
        "calendar_id": "primary",
        "summary": "Planning",
        "description": "",
        "start": "2030-01-02T10:00:00+00:00",
        "end": "2030-01-02T10:30:00+00:00",
        "time_zone": "UTC",
        "attendees": [],
        "html_link": None,
        "status": "confirmed",
    }
    monkeypatch.setattr(routes, "require_calendar_account", lambda session, user: object())
    monkeypatch.setattr(routes, "build_calendar_service", lambda account, session: object())
    monkeypatch.setattr(
        routes,
        "create_event",
        lambda service, calendar_id, payload, request_id: calls.append(
            ("create", request_id)
        )
        or event_data,
    )
    monkeypatch.setattr(
        routes,
        "update_event",
        lambda service, calendar_id, event_id, payload: calls.append(
            ("update", event_id)
        )
        or event_data,
    )
    monkeypatch.setattr(
        routes,
        "delete_event",
        lambda service, calendar_id, event_id: calls.append(("delete", event_id)),
    )
    base_payload = {
        "summary": "Planning",
        "description": "",
        "start": "2030-01-02T10:00:00Z",
        "end": "2030-01-02T10:30:00Z",
        "time_zone": "UTC",
        "attendees": [],
        "request_id": str(uuid4()),
    }
    csrf_token = client.csrf_token
    client.set_session(client.session_token, None)
    csrf_rejected = client.post(
        "/api/integrations/calendar/events",
        json={**base_payload, "confirm": True},
    )
    assert csrf_rejected.status_code == 403
    assert calls == []
    client.set_session(client.session_token, csrf_token)
    missing_confirmation = client.post(
        "/api/integrations/calendar/events",
        json=base_payload,
    )
    assert missing_confirmation.status_code == 422
    assert calls == []

    created = client.post(
        "/api/integrations/calendar/events",
        json={**base_payload, "confirm": True},
    )
    assert created.status_code == 201
    assert created.json()["id"] == "event-1"
    assert "access_token" not in created.text

    updated = client.request(
        "PUT",
        "/api/integrations/calendar/events/event-1",
        json={key: value for key, value in base_payload.items() if key != "request_id"}
        | {"confirm": True},
    )
    assert updated.status_code == 200
    deleted = client.delete(
        "/api/integrations/calendar/events/event-1",
        json={"confirm": True},
    )
    assert deleted.status_code == 204
    assert [action for action, _ in calls] == ["create", "update", "delete"]
