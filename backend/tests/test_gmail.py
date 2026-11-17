import base64
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
import httplib2
from googleapiclient.errors import HttpError
from sqlalchemy import select

from app.api.routes.gmail import GMAIL_STATE_COOKIE_NAME
from app.core.config import TokenEncryptionConfigurationError
from app.models import ConnectedAccount, Email, User
from app.services import gmail as gmail_service
from app.services.token_encryption import (
    TokenDecryptionError,
    decrypt_token,
    encrypt_token,
)
from tests.helpers import get_development_user


def configure_gmail(monkeypatch):
    key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8002/api/auth/google/callback"
    )
    monkeypatch.setenv(
        "GMAIL_REDIRECT_URI",
        "http://localhost:8002/api/integrations/gmail/callback",
    )
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY_ID", "test-key")
    return key


def gmail_message(message_id="gmail-message-1"):
    body = base64.urlsafe_b64encode(b"Hello from Gmail").decode().rstrip("=")
    return {
        "id": message_id,
        "threadId": "gmail-thread-1",
        "internalDate": "1735689600000",
        "labelIds": ["INBOX", "STARRED"],
        "snippet": "Hello from Gmail",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Sender <sender@example.test>"},
                {"name": "To", "value": "Reader <reader@example.test>"},
                {"name": "Subject", "value": "A Gmail subject"},
                {"name": "Date", "value": formatdate(usegmt=True)},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": body},
                },
                {
                    "mimeType": "text/html",
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            b"<p>Hello <script>alert(1)</script><a href='javascript:x'>link</a></p>"
                        ).decode().rstrip("=")
                    },
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "private.pdf",
                    "body": {"data": "ignored"},
                },
            ],
        },
    }


def test_token_encryption_uses_unique_authenticated_ciphertext(monkeypatch):
    configure_gmail(monkeypatch)
    account_id = uuid4()
    first = encrypt_token("sensitive-access-token", account_id, "access")
    second = encrypt_token("sensitive-access-token", account_id, "access")

    assert first != second
    assert "sensitive-access-token" not in first
    assert decrypt_token(first, account_id, "access") == "sensitive-access-token"
    with pytest.raises(TokenDecryptionError):
        decrypt_token(first, uuid4(), "access")
    with pytest.raises(TokenDecryptionError):
        decrypt_token(first, account_id, "refresh")


def test_token_encryption_rejects_invalid_keys(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "not-base64")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY_ID", "invalid")
    with pytest.raises(TokenEncryptionConfigurationError):
        encrypt_token("token", uuid4(), "access")


def test_invalid_encryption_key_does_not_destroy_stored_credentials(
    monkeypatch, db_session_factory
):
    current_key = configure_gmail(monkeypatch)
    user = User(email="key-user@example.test")
    with db_session_factory() as session:
        session.add(user)
        session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            provider_account_id="key-subject",
            status="connected",
        )
        session.add(account)
        session.flush()
        account.access_token_encrypted = encrypt_token("protected-access", account.id, "access")
        account.refresh_token_encrypted = encrypt_token("protected-refresh", account.id, "refresh")
        session.commit()
        account_id = account.id

    replacement_key = base64.urlsafe_b64encode(b"abcdef0123456789abcdef0123456789").decode()
    assert replacement_key != current_key
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", replacement_key)
    with db_session_factory() as session:
        account = session.get(ConnectedAccount, account_id)
        with pytest.raises(gmail_service.GmailAPIUnavailable):
            gmail_service._credentials_for_account(session, account)
        session.refresh(account)
        assert account.status == "connected"
        assert account.access_token_encrypted is not None
        assert account.refresh_token_encrypted is not None


def test_token_encryption_keys_rotate_lazily_on_credential_use(
    monkeypatch, db_session_factory
):
    previous_key = configure_gmail(monkeypatch)
    user = User(email="rotation-user@example.test")
    with db_session_factory() as session:
        session.add(user)
        session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            provider_account_id="rotation-subject",
            status="connected",
        )
        session.add(account)
        session.flush()
        account.access_token_encrypted = encrypt_token("access-value", account.id, "access")
        account.refresh_token_encrypted = encrypt_token("refresh-value", account.id, "refresh")
        account.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        session.commit()
        account_id = account.id

    active_key = base64.urlsafe_b64encode(b"new-key-0123456789abcdef01234567").decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", active_key)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY_ID", "new-key")
    monkeypatch.setenv(
        "TOKEN_ENCRYPTION_KEY_PREVIOUS", f"test-key:{previous_key}"
    )
    with db_session_factory() as session:
        account = session.get(ConnectedAccount, account_id)
        gmail_service._credentials_for_account(session, account)
        session.refresh(account)
        assert ".new-key." in account.access_token_encrypted
        assert ".new-key." in account.refresh_token_encrypted
        assert decrypt_token(account.access_token_encrypted, account.id, "access") == "access-value"
        assert decrypt_token(account.refresh_token_encrypted, account.id, "refresh") == "refresh-value"


def test_token_refresh_rotates_encrypted_credentials(monkeypatch, db_session_factory):
    configure_gmail(monkeypatch)
    from google.oauth2.credentials import Credentials

    user = User(email="refresh-user@example.test")
    with db_session_factory() as session:
        session.add(user)
        session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            provider_account_id="refresh-subject",
            status="connected",
        )
        session.add(account)
        session.flush()
        account.access_token_encrypted = encrypt_token("old-access", account.id, "access")
        account.refresh_token_encrypted = encrypt_token("old-refresh", account.id, "refresh")
        account.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()
        account_id = account.id

    def refresh(credentials, request):
        credentials.token = "new-access"
        credentials._refresh_token = "new-refresh"
        credentials.expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", refresh)
    monkeypatch.setattr(gmail_service, "GoogleRequest", lambda: object())

    with db_session_factory() as session:
        account = session.get(ConnectedAccount, account_id)
        credentials = gmail_service._credentials_for_account(session, account)
        session.refresh(account)
        assert credentials.token == "new-access"
        assert decrypt_token(account.access_token_encrypted, account.id, "access") == "new-access"
        assert decrypt_token(account.refresh_token_encrypted, account.id, "refresh") == "new-refresh"


def test_revoked_refresh_requires_reauthorization_without_exposing_credentials(
    monkeypatch, db_session_factory
):
    configure_gmail(monkeypatch)
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials

    user = User(email="revoked-user@example.test")
    with db_session_factory() as session:
        session.add(user)
        session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            provider_account_id="revoked-subject",
            status="connected",
        )
        session.add(account)
        session.flush()
        account.access_token_encrypted = encrypt_token("old-access", account.id, "access")
        account.refresh_token_encrypted = encrypt_token("old-refresh", account.id, "refresh")
        account.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()
        account_id = account.id

    def reject_refresh(credentials, request):
        raise RefreshError("invalid_grant")

    monkeypatch.setattr(Credentials, "refresh", reject_refresh)
    monkeypatch.setattr(gmail_service, "GoogleRequest", lambda: object())
    with db_session_factory() as session:
        account = session.get(ConnectedAccount, account_id)
        with pytest.raises(gmail_service.GmailReauthorizationRequired):
            gmail_service._credentials_for_account(session, account)
        session.refresh(account)
        assert account.status == "disconnected"
        assert account.access_token_encrypted is None
        assert account.refresh_token_encrypted is None


def test_gmail_mime_parser_extracts_plain_text_and_sanitizes_html():
    parsed = gmail_service.parse_gmail_message(gmail_message())
    assert parsed["sender"] == "Sender <sender@example.test>"
    assert parsed["recipients"] == ["Reader <reader@example.test>"]
    assert parsed["subject"] == "A Gmail subject"
    assert parsed["body"] == "Hello from Gmail"
    assert parsed["received_at"] == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert parsed["is_read"] is True
    assert parsed["is_starred"] is True
    assert "script" not in parsed["html_body"]
    assert "javascript:" not in parsed["html_body"]
    assert "private.pdf" not in parsed["body"]


def test_gmail_parser_tolerates_missing_and_malformed_fields():
    parsed = gmail_service.parse_gmail_message(
        {
            "id": "malformed-message",
            "labelIds": [{"unexpected": "value"}, "UNREAD"],
            "payload": {
                "headers": ["malformed-header", {"name": "Subject", "value": "Safe"}],
                "parts": ["malformed-part", {"mimeType": "text/plain"}],
            },
        }
    )
    assert parsed["external_message_id"] == "malformed-message"
    assert parsed["subject"] == "Safe"
    assert parsed["sender"] == "Unknown sender"
    assert parsed["is_read"] is False
    assert parsed["body"] == ""


def test_gmail_parser_marks_attachment_messages_for_safe_auto_reply_exclusion():
    parsed = gmail_service.parse_gmail_message({
        "id": "message-with-attachment",
        "payload": {"mimeType": "multipart/mixed", "parts": [
            {"mimeType": "text/plain", "body": {"data": "SGVsbG8"}},
            {"mimeType": "application/pdf", "filename": "statement.pdf", "body": {"attachmentId": "private-id"}},
        ]},
    })
    assert parsed["has_attachments"] is True


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, gmail_service.GmailReauthorizationRequired),
        (404, gmail_service.GmailHistoryExpired),
        (429, gmail_service.GmailRateLimited),
        (503, gmail_service.GmailAPIUnavailable),
    ],
)
def test_gmail_http_errors_are_mapped_without_leaking_provider_details(
    status_code, error_type
):
    class FailedRequest:
        def execute(self, num_retries=0):
            raise HttpError(
                httplib2.Response({"status": str(status_code)}),
                b"provider response containing private details",
            )

    with pytest.raises(error_type):
        gmail_service._execute(FailedRequest())


def test_gmail_api_disabled_error_is_actionable_and_logs_only_reason_code(caplog):
    class FailedRequest:
        def execute(self, num_retries=0):
            raise HttpError(
                httplib2.Response({"status": "403"}),
                b'{"error":{"errors":[{"reason":"accessNotConfigured"}],"message":"private response detail"}}',
            )

    with pytest.raises(gmail_service.GmailAPINotEnabled):
        gmail_service._execute(FailedRequest())
    assert "accessNotConfigured" in caplog.text
    assert "private response detail" not in caplog.text


def test_gmail_oauth_requires_authenticated_user_pkce_and_readonly_scope(
    client, db_session_factory, monkeypatch
):
    configure_gmail(monkeypatch)
    assert client.get("/api/integrations/gmail/connect").status_code == 405
    response = client.post("/api/integrations/gmail/connect")
    assert response.status_code == 200
    params = parse_qs(urlparse(response.json()["authorization_url"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["access_type"] == ["offline"]
    assert "https://www.googleapis.com/auth/gmail.readonly" in params["scope"][0]
    assert "gmail.send" not in params["scope"][0]
    assert params["state"][0] == response.cookies[GMAIL_STATE_COOKIE_NAME]

    with db_session_factory() as session:
        from app.models import OAuthTransaction

        transaction = session.scalar(select(OAuthTransaction))
        assert transaction.provider == "gmail"
        assert transaction.user_id is not None
        assert transaction.state_hash != params["state"][0]


def test_gmail_status_and_sync_require_authentication_and_connection(
    client, unauthenticated_client
):
    assert unauthenticated_client.get("/api/integrations/gmail/status").status_code == 401
    status = client.get("/api/integrations/gmail/status")
    assert status.status_code == 200
    assert status.json()["status"] == "not_connected"
    response = client.post("/api/integrations/gmail/sync")
    assert response.status_code == 409
    client.set_session(client.session_token, None)
    assert client.post("/api/integrations/gmail/connect").status_code == 403


def test_gmail_oauth_callback_links_identity_and_encrypts_tokens(
    client, db_session_factory, monkeypatch
):
    configure_gmail(monkeypatch)
    from app.api.routes import gmail as gmail_routes

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
        session.commit()

    monkeypatch.setattr(
        gmail_routes,
        "exchange_google_token_response",
        lambda code, verifier, config: {
            "id_token": "mock-id-token",
            "access_token": "mock-access-token",
            "refresh_token": "mock-refresh-token",
            "expires_in": 3600,
            "scope": f"openid email profile {gmail_service.GMAIL_READONLY_SCOPE}",
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

    started = client.post("/api/integrations/gmail/connect")
    params = parse_qs(urlparse(started.json()["authorization_url"]).query)
    state = params["state"][0]
    response = client.get(
        "/api/integrations/gmail/callback",
        params={"state": state, "code": "mock-code"},
        cookies={GMAIL_STATE_COOKIE_NAME: state},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "gmail=connected" in response.headers["location"]
    assert "mock-access-token" not in response.text
    with db_session_factory() as session:
        account = session.scalar(
            select(ConnectedAccount).where(ConnectedAccount.provider == "gmail")
        )
        assert account.status == "connected"
        assert account.provider_account_id == "login-subject"
        assert account.email_address == "reader@example.test"
        assert decrypt_token(account.access_token_encrypted, account.id, "access") == "mock-access-token"
        assert decrypt_token(account.refresh_token_encrypted, account.id, "refresh") == "mock-refresh-token"


def test_gmail_oauth_cancellation_is_reported_without_exchange(
    client, monkeypatch
):
    configure_gmail(monkeypatch)
    started = client.post("/api/integrations/gmail/connect")
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    response = client.get(
        "/api/integrations/gmail/callback",
        params={"state": state, "error": "access_denied"},
        cookies={GMAIL_STATE_COOKIE_NAME: state},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "gmail_error=cancelled" in response.headers["location"]


def test_gmail_callback_rejects_state_and_different_google_identity(
    client, db_session_factory, monkeypatch
):
    configure_gmail(monkeypatch)
    started = client.post("/api/integrations/gmail/connect")
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    rejected = client.get(
        "/api/integrations/gmail/callback",
        params={"state": state, "code": "mock-code"},
        cookies={GMAIL_STATE_COOKIE_NAME: "different-state"},
        follow_redirects=False,
    )
    assert rejected.status_code == 400

    from app.api.routes import gmail as gmail_routes

    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        session.add(
            ConnectedAccount(
                user_id=user.id,
                provider="google",
                provider_account_id="expected-subject",
                status="connected",
            )
        )
        session.commit()
    monkeypatch.setattr(
        gmail_routes,
        "exchange_google_token_response",
        lambda code, verifier, config: {
            "id_token": "mock",
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
            "scope": gmail_service.GMAIL_READONLY_SCOPE,
        },
    )
    monkeypatch.setattr(
        gmail_routes,
        "verify_google_identity",
        lambda token, client_id: {
            "sub": "other-subject",
            "email": "other@example.test",
            "email_verified": True,
        },
    )
    started = client.post("/api/integrations/gmail/connect")
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    rejected = client.get(
        "/api/integrations/gmail/callback",
        params={"state": state, "code": "mock-code"},
        cookies={GMAIL_STATE_COOKIE_NAME: state},
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    assert "gmail_error=authorization_failed" in rejected.headers["location"]
    with db_session_factory() as session:
        assert session.scalar(
            select(ConnectedAccount).where(ConnectedAccount.provider == "gmail")
        ) is None


def test_gmail_listing_is_user_scoped_read_only_and_separate_from_sample(
    client, db_session_factory, monkeypatch
):
    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        session.add_all(
            [
                ConnectedAccount(
                    user_id=user.id,
                    provider="gmail",
                    provider_account_id="gmail-subject",
                    status="connected",
                ),
                Email(
                    user_id=user.id,
                    source="sample",
                    sender="Sample sender",
                    subject="Sample only",
                ),
                Email(
                    user_id=user.id,
                    source="gmail",
                    external_message_id="gmail-id",
                    thread_id="gmail-thread",
                    sender="Actual sender",
                    subject="Gmail only",
                ),
            ]
        )
        session.commit()
        gmail_email = session.scalar(
            select(Email).where(Email.source == "gmail")
        )
        gmail_email_id = gmail_email.id
        other_user = User(email="different-gmail-user@example.test")
        session.add(other_user)
        session.flush()
        session.add(
            Email(
                user_id=other_user.id,
                source="gmail",
                external_message_id="other-gmail-id",
                sender="Other user sender",
                subject="Private Gmail",
            )
        )
        session.commit()

    listing = client.get("/api/emails")
    assert listing.status_code == 200
    assert [item["subject"] for item in listing.json()["items"]] == ["Gmail only"]
    update = client.patch(
        f"/api/emails/{gmail_email_id}", json={"is_read": True}
    )
    assert update.status_code == 409
    assert client.get(f"/api/emails/{uuid4()}").status_code == 404
    assert "private-access-token" not in listing.text

    from app.api.routes import emails as email_routes

    monkeypatch.setattr(
        email_routes,
        "sync_thread",
        lambda session, user, account, thread_id: [
            session.get(Email, gmail_email_id)
        ],
    )
    thread = client.get(f"/api/emails/{gmail_email_id}/thread")
    assert thread.status_code == 200
    assert [item["subject"] for item in thread.json()["messages"]] == ["Gmail only"]


def test_gmail_sync_is_idempotent_and_thread_upserts_messages(
    db_session_factory, monkeypatch
):
    configure_gmail(monkeypatch)
    user = User(email="sync-user@example.test")
    with db_session_factory() as session:
        session.add(user)
        session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            provider_account_id="sync-subject",
            status="connected",
        )
        session.add(account)
        session.commit()
        account_id = account.id
        user_id = user.id

    class Request:
        def __init__(self, value):
            self.value = value

        def execute(self, num_retries=0):
            return self.value

    class History:
        def list(self, **kwargs):
            return Request(
                {
                    "history": [
                        {"messagesAdded": [{"message": {"id": "gmail-message-1"}}]}
                    ]
                }
            )

    class Users:
        def history(self):
            return History()

    class Service:
        def users(self):
            return Users()

    monkeypatch.setattr(gmail_service, "build_gmail_service", lambda account, session: Service())
    monkeypatch.setattr(gmail_service, "fetch_profile", lambda service: {"historyId": "history-new"})
    monkeypatch.setattr(gmail_service, "fetch_message", lambda service, message_id: gmail_message(message_id))

    with db_session_factory() as session:
        account = session.get(ConnectedAccount, account_id)
        account.gmail_history_id = "history-old"
        session.commit()
        first = gmail_service.sync_gmail(session, session.get(User, user_id), account)
        account.gmail_history_id = "history-old"
        session.commit()
        second = gmail_service.sync_gmail(session, session.get(User, user_id), account)
        records = session.scalars(
            select(Email).where(
                Email.user_id == user_id,
                Email.source == "gmail",
                Email.external_message_id == "gmail-message-1",
            )
        ).all()
        assert first["synced"] == second["synced"] == 1
        assert len(records) == 1


def test_incremental_history_limit_resumes_without_skipping_messages(
    db_session_factory, monkeypatch
):
    configure_gmail(monkeypatch)
    user = User(email="cursor-user@example.test")
    with db_session_factory() as session:
        session.add(user)
        session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            provider_account_id="cursor-subject",
            status="connected",
            gmail_history_id="history-old",
        )
        session.add(account)
        session.commit()
        account_id = account.id
        user_id = user.id

    class Request:
        def execute(self, num_retries=0):
            return {
                "history": [
                    {
                        "messagesAdded": [
                            {"message": {"id": "message-one"}},
                            {"message": {"id": "message-two"}},
                        ]
                    }
                ]
            }

    class History:
        def list(self, **kwargs):
            return Request()

    class Users:
        def history(self):
            return History()

    class Service:
        def users(self):
            return Users()

    monkeypatch.setattr(gmail_service, "get_gmail_sync_limit", lambda: 1)
    monkeypatch.setattr(gmail_service, "build_gmail_service", lambda account, session: Service())
    monkeypatch.setattr(gmail_service, "fetch_profile", lambda service: {"historyId": "history-current"})
    monkeypatch.setattr(
        gmail_service,
        "fetch_message",
        lambda service, message_id: gmail_message(message_id),
    )

    with db_session_factory() as session:
        account = session.get(ConnectedAccount, account_id)
        user = session.get(User, user_id)
        first = gmail_service.sync_gmail(session, user, account)
        session.refresh(account)
        assert first == {"synced": 1, "incremental": True}
        assert account.gmail_pending_message_ids == ["message-two"]
        assert account.gmail_pending_history_id == "history-current"
        assert account.gmail_history_id == "history-old"

        second = gmail_service.sync_gmail(session, user, account)
        session.refresh(account)
        assert second == {"synced": 1, "incremental": True}
        assert account.gmail_history_id == "history-current"
        assert account.gmail_pending_message_ids == []
        assert account.gmail_pending_history_id is None
        assert {
            email.external_message_id
            for email in session.scalars(
                select(Email).where(Email.user_id == user_id, Email.source == "gmail")
            )
        } == {"message-one", "message-two"}
