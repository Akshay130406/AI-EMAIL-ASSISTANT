from datetime import datetime, timedelta, timezone
import base64
from urllib.parse import parse_qs, urlparse
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select

from app.api.dependencies import SESSION_COOKIE_NAME
from app.api.routes.auth import OAUTH_STATE_COOKIE_NAME
from app.core.config import (
    ConfigurationError,
    validate_production_config,
    validate_runtime_config,
)
from app.models import ConnectedAccount, OAuthTransaction, User, UserSession
from app.services.auth import (
    GoogleIdentityError,
    create_or_link_google_user,
    token_digest,
)
from app.services.google_oauth import GoogleOAuthError


def configure_google(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv(
        "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/google/callback"
    )
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")


def start_oauth(client):
    response = client.get("/api/auth/google", follow_redirects=False)
    assert response.status_code == 302
    authorization = parse_qs(urlparse(response.headers["location"]).query)
    return response, authorization


def test_google_login_uses_pkce_least_privilege_and_secure_state(
    client, db_session_factory, monkeypatch
):
    configure_google(monkeypatch)
    response, authorization = start_oauth(client)

    assert authorization["scope"] == ["openid email profile"]
    assert authorization["code_challenge_method"] == ["S256"]
    assert authorization["client_id"] == ["test-client-id"]
    assert authorization["state"][0] == response.cookies.get(OAUTH_STATE_COOKIE_NAME)
    assert "gmail" not in authorization["scope"][0].lower()
    assert "calendar" not in authorization["scope"][0].lower()
    assert "httponly" in response.headers["set-cookie"].lower()

    with db_session_factory() as session:
        transaction = session.scalar(select(OAuthTransaction))
        assert transaction is not None
        assert transaction.state_hash == token_digest(authorization["state"][0])
        assert len(transaction.code_verifier) >= 43


@pytest.mark.parametrize(
    ("params", "cookies", "detail"),
    [
        ({}, {}, "OAuth state is required"),
        ({"state": "unknown", "code": "code"}, {OAUTH_STATE_COOKIE_NAME: "unknown"}, "OAuth state validation failed"),
        ({"state": "state"}, {OAUTH_STATE_COOKIE_NAME: "state"}, "OAuth state validation failed"),
    ],
)
def test_callback_rejects_missing_invalid_or_incomplete_parameters(
    client, params, cookies, detail
):
    response = client.get(
        "/api/auth/google/callback",
        params=params,
        cookies=cookies,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == detail


def test_callback_handles_provider_cancellation(client, monkeypatch):
    configure_google(monkeypatch)
    login_response, authorization = start_oauth(client)
    state = authorization["state"][0]
    response = client.get(
        "/api/auth/google/callback",
        params={"state": state, "error": "access_denied"},
        cookies={OAUTH_STATE_COOKIE_NAME: state},
    )

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173/login?auth_error=cancelled"
    assert OAUTH_STATE_COOKIE_NAME in response.headers["set-cookie"]
    assert login_response.cookies.get(OAUTH_STATE_COOKIE_NAME) == state


def test_oauth_transaction_expires(client, db_session_factory, monkeypatch):
    configure_google(monkeypatch)
    _, authorization = start_oauth(client)
    state = authorization["state"][0]
    with db_session_factory() as session:
        transaction = session.scalar(select(OAuthTransaction))
        transaction.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    response = client.get(
        "/api/auth/google/callback",
        params={"state": state, "code": "mock-code"},
        cookies={OAUTH_STATE_COOKIE_NAME: state},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "OAuth state validation failed"


def test_google_identity_creation_is_idempotent(db_session_factory):
    identity = {
        "sub": "new-google-subject",
        "email": "new-user@example.test",
        "email_verified": True,
        "name": "New User",
    }
    with db_session_factory() as session:
        first = create_or_link_google_user(session, identity)
        first_id = first.id
        second = create_or_link_google_user(session, identity)
        assert second.id == first_id
        assert session.scalar(
            select(ConnectedAccount).where(
                ConnectedAccount.provider_account_id == "new-google-subject"
            )
        ).user_id == first_id


def test_existing_email_with_different_google_subject_is_not_auto_linked(
    db_session_factory,
):
    with db_session_factory() as session:
        user = User(email="linked@example.test")
        session.add(user)
        session.flush()
        session.add(
            ConnectedAccount(
                user_id=user.id,
                provider="google",
                provider_account_id="original-subject",
                status="connected",
            )
        )
        session.commit()

        with pytest.raises(GoogleIdentityError):
            create_or_link_google_user(
                session,
                {
                    "sub": "different-subject",
                    "email": "linked@example.test",
                    "email_verified": True,
                },
            )
        assert session.scalar(
            select(ConnectedAccount).where(
                ConnectedAccount.provider_account_id == "different-subject"
            )
        ) is None


def test_successful_callback_links_identity_rotates_session_and_returns_safe_profile(
    client, db_session_factory, monkeypatch
):
    from app.api.routes import auth

    configure_google(monkeypatch)
    monkeypatch.setattr(auth, "exchange_google_code", lambda code, verifier, config: "mock-id-token")
    monkeypatch.setattr(
        auth,
        "verify_google_identity",
        lambda identity_token, client_id: {
            "sub": "google-subject-123",
            "email": "developer@example.test",
            "email_verified": True,
            "name": "Verified Test User",
            "picture": "https://example.test/avatar.png",
        },
    )
    old_token = client.session_token
    old_hash = token_digest(old_token)
    _, authorization = start_oauth(client)
    state = authorization["state"][0]
    callback = client.get(
        "/api/auth/google/callback",
        params={"state": state, "code": "mock-authorization-code"},
        cookies={OAUTH_STATE_COOKIE_NAME: state},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert callback.headers["location"] == "http://localhost:5173"
    assert "access_token" not in callback.text
    assert "refresh_token" not in callback.text
    assert "httponly" in callback.headers["set-cookie"].lower()
    new_token = callback.cookies.get(SESSION_COOKIE_NAME)
    assert new_token and new_token != old_token

    client.set_session(new_token, None)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "developer@example.test"
    assert me.json()["user"]["display_name"] == "Verified Test User"
    assert me.json()["user"]["picture_url"] == "https://example.test/avatar.png"
    assert "csrf_token" in me.json()
    assert "access_token" not in me.text
    assert "refresh_token" not in me.text
    client.set_session(new_token, me.json()["csrf_token"])

    with db_session_factory() as session:
        accounts = session.scalars(
            select(ConnectedAccount).where(ConnectedAccount.provider == "google")
        ).all()
        assert len(accounts) == 1
        assert accounts[0].provider_account_id == "google-subject-123"
        assert session.scalar(
            select(UserSession).where(UserSession.session_token_hash == old_hash)
        ) is None

    client.set_session(old_token, None)
    assert client.get("/api/auth/me").status_code == 401


def test_existing_google_identity_resolves_to_its_existing_owner(
    client, db_session_factory, monkeypatch
):
    from app.api.routes import auth

    configure_google(monkeypatch)
    with db_session_factory() as session:
        other_user = User(email="different@example.test")
        session.add(other_user)
        session.flush()
        session.add(
            ConnectedAccount(
                user_id=other_user.id,
                provider="google",
                provider_account_id="already-linked-subject",
                status="connected",
            )
        )
        session.commit()

    monkeypatch.setattr(auth, "exchange_google_code", lambda *_args: "mock-id-token")
    monkeypatch.setattr(
        auth,
        "verify_google_identity",
        lambda *_args: {
            "sub": "already-linked-subject",
            "email": "developer@example.test",
            "email_verified": True,
        },
    )
    _, authorization = start_oauth(client)
    state = authorization["state"][0]
    response = client.get(
        "/api/auth/google/callback",
        params={"state": state, "code": "mock-code"},
        cookies={OAUTH_STATE_COOKIE_NAME: state},
    )

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173"
    client.set_session(response.cookies.get(SESSION_COOKIE_NAME), None)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "different@example.test"


def test_unverified_google_email_is_rejected(client, monkeypatch):
    from app.api.routes import auth

    configure_google(monkeypatch)
    monkeypatch.setattr(auth, "exchange_google_code", lambda *_args: "mock-id-token")
    monkeypatch.setattr(
        auth,
        "verify_google_identity",
        lambda *_args: {
            "sub": "unverified-subject",
            "email": "developer@example.test",
            "email_verified": False,
        },
    )
    _, authorization = start_oauth(client)
    state = authorization["state"][0]
    response = client.get(
        "/api/auth/google/callback",
        params={"state": state, "code": "mock-code"},
        cookies={OAUTH_STATE_COOKIE_NAME: state},
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("/login?auth_error=sign_in_failed")


def test_token_exchange_provider_failure_is_reported_without_details(
    client, monkeypatch
):
    from app.api.routes import auth

    configure_google(monkeypatch)
    def fail_exchange(*_args):
        raise GoogleOAuthError("provider detail")

    monkeypatch.setattr(auth, "exchange_google_code", fail_exchange)
    _, authorization = start_oauth(client)
    state = authorization["state"][0]
    response = client.get(
        "/api/auth/google/callback",
        params={"state": state, "code": "mock-code"},
        cookies={OAUTH_STATE_COOKIE_NAME: state},
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("/login?auth_error=sign_in_failed")


def test_oauth_database_failure_redirects_to_recoverable_login_error(client, monkeypatch):
    from app.api.routes import auth

    configure_google(monkeypatch)

    def fail_transaction(*_args, **_kwargs):
        raise SQLAlchemyError("database detail must not escape")

    monkeypatch.setattr(auth, "create_oauth_transaction", fail_transaction)
    response = client.get("/api/auth/google", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == (
        "http://localhost:5173/login?auth_error=service_unavailable"
    )
    assert "database detail" not in response.text


def test_invalid_frontend_redirect_uses_safe_local_fallback(client, monkeypatch):
    from app.api.routes import auth

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FRONTEND_URL", "https://attacker.example/path")

    response = auth._login_error_redirect("sign_in_failed")

    assert response.headers["location"] == (
        "http://127.0.0.1:5174/login?auth_error=sign_in_failed"
    )
    assert "provider detail" not in response.headers["location"]


def test_expired_session_is_rejected(client, db_session_factory):
    session_hash = token_digest(client.session_token)
    with db_session_factory() as session:
        auth_session = session.scalar(
            select(UserSession).where(UserSession.session_token_hash == session_hash)
        )
        auth_session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    assert client.get("/api/auth/me").status_code == 401


def test_logout_revokes_session_and_requires_csrf(client):
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "invalid"}).status_code == 403
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert SESSION_COOKIE_NAME in response.headers["set-cookie"]
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/me",
        "/api/dashboard/overview",
        "/api/emails",
        "/api/drafts",
        "/api/conversations",
        "/api/settings",
    ],
)
def test_data_and_identity_endpoints_reject_unauthenticated_requests(
    unauthenticated_client, path
):
    assert unauthenticated_client.get(path).status_code == 401


def test_mutations_require_allowed_origin_and_csrf(client):
    response = client.post(
        "/api/drafts",
        json={"subject": "Blocked request"},
        headers={"Origin": "https://attacker.example", "X-CSRF-Token": client.csrf_token},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF validation failed"


def test_production_configuration_fails_closed_when_incomplete(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for key in (
        "DATABASE_URL",
        "FRONTEND_URL",
        "BACKEND_URL",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "SESSION_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ConfigurationError):
        validate_production_config()


def configure_production(monkeypatch, database_url):
    settings = {
        "APP_ENV": "production",
        "DATABASE_URL": database_url,
        "FRONTEND_URL": "https://mailmind.example",
        "BACKEND_URL": "https://api.mailmind.example",
        "GOOGLE_CLIENT_ID": "test-client-id",
        "GOOGLE_CLIENT_SECRET": "test-client-secret",
        "GOOGLE_REDIRECT_URI": "https://api.mailmind.example/api/auth/google/callback",
        "GMAIL_REDIRECT_URI": "https://api.mailmind.example/api/integrations/gmail/callback",
        "CALENDAR_REDIRECT_URI": "https://api.mailmind.example/api/integrations/calendar/callback",
        "SESSION_SECRET": "test-session-secret-with-more-than-thirty-two-characters",
        "TOKEN_ENCRYPTION_KEY_ID": "test",
        "TOKEN_ENCRYPTION_KEY": base64.b64encode(b"x" * 32).decode("ascii"),
        "ALLOWED_ORIGINS": "https://mailmind.example",
        "COOKIE_SECURE": "true",
        "COOKIE_SAMESITE": "none",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)


def test_production_configuration_rejects_sqlite_database(monkeypatch):
    configure_production(monkeypatch, "sqlite:///./mailmind.db")

    with pytest.raises(ConfigurationError, match="must use PostgreSQL"):
        validate_production_config()


def test_production_configuration_accepts_postgresql_url(monkeypatch):
    configure_production(
        monkeypatch, "postgresql://user:password@db.example/mailmind"
    )

    validate_production_config()


def test_runtime_cors_rejects_wildcard_origins(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    with pytest.raises(ConfigurationError):
        validate_runtime_config()
