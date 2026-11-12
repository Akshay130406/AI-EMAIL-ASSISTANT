import base64
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httplib2
import pytest
from googleapiclient.errors import HttpError
from sqlalchemy import select

from app.api.routes.gmail import GMAIL_STATE_COOKIE_NAME
from app.core.config import TokenEncryptionConfigurationError
from app.models import ConnectedAccount, Draft, Email, User
from app.services import gmail as gmail_service
from app.services.token_encryption import encrypt_token
from tests.helpers import get_development_user


def _configure_gmail(monkeypatch):
    key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "http://localhost:8000/api/integrations/gmail/callback")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY_ID", "test-key")


def _add_connected_account(db_session_factory, user_id, *, compose=True):
    with db_session_factory() as session:
        account = ConnectedAccount(
            user_id=user_id,
            provider="gmail",
            provider_account_id=f"gmail-subject-{user_id}",
            status="connected",
            granted_scopes=[
                gmail_service.GMAIL_READONLY_SCOPE,
                *([gmail_service.GMAIL_COMPOSE_SCOPE] if compose else []),
            ],
        )
        session.add(account)
        session.flush()
        account.access_token_encrypted = encrypt_token("access", account.id, "access")
        account.refresh_token_encrypted = encrypt_token("refresh", account.id, "refresh")
        session.commit()
        return account.id


def test_compose_oauth_is_separate_and_requests_only_compose_scope(
    client, db_session_factory, monkeypatch
):
    _configure_gmail(monkeypatch)
    user = get_development_user(db_session_factory)
    _add_connected_account(db_session_factory, user.id, compose=False)

    response = client.post("/api/integrations/gmail/compose/connect")
    assert response.status_code == 200
    params = parse_qs(urlparse(response.json()["authorization_url"]).query)
    scopes = params["scope"][0].split()
    assert gmail_service.GMAIL_READONLY_SCOPE in scopes
    assert gmail_service.GMAIL_COMPOSE_SCOPE in scopes
    assert "https://www.googleapis.com/auth/gmail.modify" not in scopes
    assert params["include_granted_scopes"] == ["true"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"][0] == response.cookies[GMAIL_STATE_COOKIE_NAME]


def test_compose_oauth_callback_requires_scope_and_preserves_identity(
    client, db_session_factory, monkeypatch
):
    _configure_gmail(monkeypatch)
    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        session.add(
            ConnectedAccount(
                user_id=user.id,
                provider="google",
                provider_account_id="login-subject",
                status="connected",
            )
        )
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            provider_account_id="login-subject",
            status="connected",
            granted_scopes=[gmail_service.GMAIL_READONLY_SCOPE],
        )
        session.add(account)
        session.flush()
        account.access_token_encrypted = encrypt_token("old-access", account.id, "access")
        account.refresh_token_encrypted = encrypt_token("old-refresh", account.id, "refresh")
        session.commit()

    from app.api.routes import gmail as gmail_routes

    monkeypatch.setattr(
        gmail_routes,
        "exchange_google_token_response",
        lambda code, verifier, config: {
            "id_token": "mock-id-token",
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "scope": (
                f"openid email profile {gmail_service.GMAIL_READONLY_SCOPE} "
                f"{gmail_service.GMAIL_COMPOSE_SCOPE}"
            ),
        },
    )
    monkeypatch.setattr(
        gmail_routes,
        "verify_google_identity",
        lambda token, client_id: {
            "sub": "login-subject",
            "email": "reader@example.test",
            "email_verified": True,
        },
    )

    started = client.post("/api/integrations/gmail/compose/connect")
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    response = client.get(
        "/api/integrations/gmail/callback",
        params={"state": state, "code": "mock-code"},
        cookies={GMAIL_STATE_COOKIE_NAME: state},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "gmail=compose_connected" in response.headers["location"]
    status_response = client.get("/api/integrations/gmail/status")
    assert status_response.json()["compose_enabled"] is True
    with db_session_factory() as session:
        account = session.scalar(
            select(ConnectedAccount).where(ConnectedAccount.provider == "gmail")
        )
        assert account.provider_account_id == "login-subject"
        assert gmail_service.GMAIL_COMPOSE_SCOPE in account.granted_scopes
        assert "new-access" not in account.access_token_encrypted


def test_compose_permission_is_required_and_user_scoped(
    client, db_session_factory, monkeypatch
):
    _configure_gmail(monkeypatch)
    user = get_development_user(db_session_factory)
    _add_connected_account(db_session_factory, user.id)
    with db_session_factory() as session:
        foreign_user = User(email="foreign@example.test")
        session.add(foreign_user)
        session.flush()
        foreign_draft = Draft(
            user_id=foreign_user.id,
            gmail_draft_id="foreign-draft",
            send_status="not_sent",
        )
        session.add(foreign_draft)
        session.commit()
        foreign_id = foreign_draft.id

    assert client.get(f"/api/integrations/gmail/drafts/{foreign_id}").status_code == 404

    with db_session_factory() as session:
        account = session.scalar(
            select(ConnectedAccount).where(ConnectedAccount.user_id == user.id)
        )
        account.granted_scopes = [gmail_service.GMAIL_READONLY_SCOPE]
        session.commit()
    response = client.get("/api/integrations/gmail/drafts")
    assert response.status_code == 409


def test_create_and_update_gmail_draft_are_user_scoped_and_validated(
    client, db_session_factory, monkeypatch
):
    _configure_gmail(monkeypatch)
    user = get_development_user(db_session_factory)
    account_id = _add_connected_account(db_session_factory, user.id)
    from app.api.routes import gmail_drafts as routes

    def account_for_user(session, current_user):
        return session.get(ConnectedAccount, account_id)

    monkeypatch.setattr(routes, "require_gmail_compose_account", account_for_user)
    monkeypatch.setattr(routes, "build_gmail_service", lambda account, session: object())
    monkeypatch.setattr(
        routes,
        "create_remote_gmail_draft",
        lambda service, raw: {
            "id": "gmail-draft-1",
            "message": {"id": "gmail-message-1", "payload": {"headers": []}},
        },
    )
    payload = {
        "recipients": ["recipient@example.test"],
        "cc": [],
        "bcc": [],
        "subject": "Hello",
        "body": "A message",
    }
    response = client.post("/api/integrations/gmail/drafts", json=payload)
    assert response.status_code == 201
    assert response.json()["gmail_draft_id"] == "gmail-draft-1"
    assert response.json()["send_status"] == "not_sent"
    draft_id = response.json()["id"]

    monkeypatch.setattr(
        routes,
        "update_remote_gmail_draft",
        lambda service, gmail_draft_id, raw: {
            "message": {"id": "gmail-message-2", "payload": {"headers": []}}
        },
    )
    payload["subject"] = "Updated"
    updated = client.request(
        "PUT", f"/api/integrations/gmail/drafts/{draft_id}", json=payload
    )
    assert updated.status_code == 200
    assert updated.json()["subject"] == "Updated"
    assert updated.json()["gmail_message_id"] == "gmail-message-2"

    payload["cc"] = ["recipient@example.test"]
    assert client.post("/api/integrations/gmail/drafts", json=payload).status_code == 422


def test_list_fetch_and_delete_gmail_drafts(client, db_session_factory, monkeypatch):
    _configure_gmail(monkeypatch)
    user = get_development_user(db_session_factory)
    account_id = _add_connected_account(db_session_factory, user.id)
    from app.api.routes import gmail_drafts as routes

    monkeypatch.setattr(
        routes,
        "require_gmail_compose_account",
        lambda session, current_user: session.get(ConnectedAccount, account_id),
    )
    service = object()
    monkeypatch.setattr(routes, "build_gmail_service", lambda account, session: service)
    monkeypatch.setattr(
        routes,
        "list_remote_gmail_drafts",
        lambda gmail_service, maximum: [{"id": "remote-draft"}],
    )
    body = base64.urlsafe_b64encode(b"Draft body").decode().rstrip("=")
    message = {
        "id": "remote-message",
        "payload": {
            "headers": [
                {"name": "To", "value": "to@example.test"},
                {"name": "Cc", "value": "cc@example.test"},
                {"name": "Bcc", "value": "bcc@example.test"},
                {"name": "Subject", "value": "Imported draft"},
            ],
            "mimeType": "text/plain",
            "body": {"data": body},
        },
    }
    fetched = []

    def get_remote(gmail_service, gmail_draft_id):
        fetched.append(gmail_draft_id)
        return {"id": gmail_draft_id, "message": message}

    monkeypatch.setattr(routes, "get_remote_gmail_draft", get_remote)
    response = client.get("/api/integrations/gmail/drafts")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["body"] == "Draft body"
    assert response.json()["items"][0]["cc"] == ["cc@example.test"]
    assert response.json()["items"][0]["bcc"] == ["bcc@example.test"]
    draft_id = response.json()["items"][0]["id"]

    detail = client.get(f"/api/integrations/gmail/drafts/{draft_id}")
    assert detail.status_code == 200
    assert detail.json()["subject"] == "Imported draft"
    assert fetched == ["remote-draft", "remote-draft"]

    deleted = []
    monkeypatch.setattr(
        routes,
        "delete_remote_gmail_draft",
        lambda gmail_service, gmail_draft_id: deleted.append(gmail_draft_id),
    )
    assert client.delete(f"/api/integrations/gmail/drafts/{draft_id}").status_code == 204
    assert deleted == ["remote-draft"]
    assert client.get(f"/api/integrations/gmail/drafts/{draft_id}").status_code == 404


def test_send_is_explicit_and_ambiguous_result_cannot_be_retried(
    client, db_session_factory, monkeypatch
):
    _configure_gmail(monkeypatch)
    user = get_development_user(db_session_factory)
    account_id = _add_connected_account(db_session_factory, user.id)
    with db_session_factory() as session:
        draft = Draft(
            user_id=user.id,
            gmail_draft_id="sendable-draft",
            send_status="not_sent",
        )
        session.add(draft)
        session.commit()
        draft_id = draft.id

    from app.api.routes import gmail_drafts as routes

    monkeypatch.setattr(
        routes, "require_gmail_compose_account", lambda session, user: session.get(ConnectedAccount, account_id)
    )
    monkeypatch.setattr(routes, "build_gmail_service", lambda account, session: object())
    attempts = 0

    def ambiguous_send(service, gmail_draft_id):
        nonlocal attempts
        attempts += 1
        raise gmail_service.GmailWriteOutcomeUnknown

    monkeypatch.setattr(routes, "send_remote_gmail_draft", ambiguous_send)
    assert client.post(
        f"/api/integrations/gmail/drafts/{draft_id}/send",
        json={"confirm": False},
    ).status_code == 422
    response = client.post(
        f"/api/integrations/gmail/drafts/{draft_id}/send",
        json={"confirm": True},
    )
    assert response.status_code == 502
    assert "do not retry" in response.json()["detail"]
    assert attempts == 1
    status_response = client.get(
        f"/api/integrations/gmail/drafts/{draft_id}/send-status"
    )
    assert status_response.json()["status"] == "unknown"
    assert client.post(
        f"/api/integrations/gmail/drafts/{draft_id}/send",
        json={"confirm": True},
    ).status_code == 409
    assert attempts == 1


def test_confirmed_send_records_message_id_and_rejects_repeated_send(
    client, db_session_factory, monkeypatch
):
    _configure_gmail(monkeypatch)
    user = get_development_user(db_session_factory)
    account_id = _add_connected_account(db_session_factory, user.id)
    with db_session_factory() as session:
        draft = Draft(
            user_id=user.id,
            gmail_draft_id="sendable-draft",
            send_status="not_sent",
        )
        session.add(draft)
        session.commit()
        draft_id = draft.id

    from app.api.routes import gmail_drafts as routes

    monkeypatch.setattr(
        routes, "require_gmail_compose_account", lambda session, user: session.get(ConnectedAccount, account_id)
    )
    monkeypatch.setattr(routes, "build_gmail_service", lambda account, session: object())
    sends = []
    monkeypatch.setattr(
        routes,
        "send_remote_gmail_draft",
        lambda service, gmail_draft_id: sends.append(gmail_draft_id) or {"id": "sent-message"},
    )
    response = client.post(
        f"/api/integrations/gmail/drafts/{draft_id}/send",
        json={"confirm": True},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert response.json()["gmail_message_id"] == "sent-message"
    with db_session_factory() as session:
        sent_email = session.scalar(
            select(Email).where(
                Email.user_id == user.id,
                Email.external_message_id == "sent-message",
            )
        )
        assert sent_email.is_sent is True
        assert sent_email.subject == ""
        assert sent_email.body == ""
    assert client.post(
        f"/api/integrations/gmail/drafts/{draft_id}/send",
        json={"confirm": True},
    ).status_code == 409
    assert sends == ["sendable-draft"]


def test_gmail_draft_mutations_require_csrf_and_foreign_drafts_are_inaccessible(
    client, db_session_factory, monkeypatch
):
    _configure_gmail(monkeypatch)
    user = get_development_user(db_session_factory)
    _add_connected_account(db_session_factory, user.id)
    with db_session_factory() as session:
        owned_draft = Draft(
            user_id=user.id,
            gmail_draft_id="owned-csrf-draft",
            send_status="not_sent",
        )
        foreign_user = User(email="foreign-draft-owner@example.test")
        session.add(owned_draft)
        session.add(foreign_user)
        session.flush()
        foreign_draft = Draft(
            user_id=foreign_user.id,
            gmail_draft_id="foreign-owned-draft",
            send_status="not_sent",
        )
        session.add(foreign_draft)
        session.commit()
        foreign_id = foreign_draft.id
        owned_id = owned_draft.id

    csrf_token = client.csrf_token
    client.set_session(client.session_token, None)
    payload = {
        "recipients": ["recipient@example.test"],
        "cc": [],
        "bcc": [],
        "subject": "Protected",
        "body": "Must not reach Gmail",
    }
    assert client.post("/api/integrations/gmail/drafts", json=payload).status_code == 403
    assert client.post(
        f"/api/integrations/gmail/drafts/{owned_id}/send",
        json={"confirm": True},
    ).status_code == 403
    client.set_session(client.session_token, csrf_token)
    assert client.get(f"/api/integrations/gmail/drafts/{foreign_id}").status_code == 404
    assert client.request(
        "PUT", f"/api/integrations/gmail/drafts/{foreign_id}", json=payload
    ).status_code == 404
    assert client.delete(f"/api/integrations/gmail/drafts/{foreign_id}").status_code == 404
    assert client.post(
        f"/api/integrations/gmail/drafts/{foreign_id}/send",
        json={"confirm": True},
    ).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"recipients": [], "cc": [], "bcc": [], "subject": "", "body": ""},
        {"recipients": ["bad-address"], "cc": [], "bcc": [], "subject": "", "body": ""},
        {
            "recipients": ["recipient@example.test"],
            "cc": ["recipient@example.test"],
            "bcc": [],
            "subject": "",
            "body": "",
        },
        {
            "recipients": ["recipient@example.test"],
            "cc": [],
            "bcc": ["bad-address"],
            "subject": "",
            "body": "",
        },
    ],
)
def test_gmail_draft_recipient_validation_rejects_invalid_addresses(client, payload):
    assert client.post("/api/integrations/gmail/drafts", json=payload).status_code == 422


def test_gmail_draft_provider_permission_and_rate_limit_errors_are_safe(
    client, db_session_factory, monkeypatch
):
    _configure_gmail(monkeypatch)
    user = get_development_user(db_session_factory)
    account_id = _add_connected_account(db_session_factory, user.id)
    from app.api.routes import gmail_drafts as routes

    monkeypatch.setattr(
        routes,
        "require_gmail_compose_account",
        lambda session, current_user: session.get(ConnectedAccount, account_id),
    )
    monkeypatch.setattr(routes, "build_gmail_service", lambda account, session: object())
    monkeypatch.setattr(
        routes,
        "create_remote_gmail_draft",
        lambda service, raw: (_ for _ in ()).throw(gmail_service.GmailRateLimited()),
    )
    payload = {
        "recipients": ["recipient@example.test"],
        "cc": [],
        "bcc": [],
        "subject": "Rate limited",
        "body": "A message",
    }
    limited = client.post("/api/integrations/gmail/drafts", json=payload)
    assert limited.status_code == 429
    assert "access" not in limited.text.lower()

    class FailedRequest:
        def execute(self):
            raise HttpError(
                httplib2.Response({"status": "403"}),
                b'{"error":{"errors":[{"reason":"insufficientPermissions"}]}}',
            )

    with pytest.raises(gmail_service.GmailReauthorizationRequired):
        gmail_service._execute_write(FailedRequest())


def test_gmail_write_request_is_never_retried():
    class FailedRequest:
        calls = 0

        def execute(self, num_retries=0):
            self.calls += 1
            raise HttpError(
                httplib2.Response({"status": "503"}),
                b"provider details are private",
            )

    request = FailedRequest()
    with pytest.raises(gmail_service.GmailWriteOutcomeUnknown):
        gmail_service._execute_write(request)
    assert request.calls == 1
