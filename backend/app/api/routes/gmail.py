import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    CurrentUser,
    CsrfProtectedUser,
    DatabaseSession,
    SESSION_COOKIE_NAME,
)
from app.core.config import (
    ConfigurationError,
    get_cookie_samesite,
    get_cookie_secure,
    get_frontend_url,
    get_gmail_oauth_config,
)
from app.database.session import get_db
from app.models import ConnectedAccount, OAuthTransaction, User
from app.schemas.gmail import GmailConnectRead, GmailStatusRead, GmailSyncRead
from app.services.auth import (
    OAuthStateError,
    consume_oauth_transaction,
    create_oauth_transaction,
)
from app.services.gmail import (
    GMAIL_PROVIDER,
    GMAIL_COMPOSE_SCOPE,
    GMAIL_READONLY_SCOPE,
    GmailAPIUnavailable,
    GmailAPINotEnabled,
    GmailNotConnected,
    GmailRateLimited,
    GmailReauthorizationRequired,
    disconnect_gmail,
    gmail_status,
    require_gmail_account,
    sync_gmail,
)
from app.services.google_oauth import (
    GoogleOAuthError,
    exchange_google_token_response,
    verify_google_identity,
)
from app.services.token_encryption import encrypt_token
from app.services.auth import GoogleIdentityError
from app.services.auth import token_digest

router = APIRouter(prefix="/integrations/gmail", tags=["Gmail integration"])
logger = logging.getLogger(__name__)
GMAIL_STATE_COOKIE_NAME = "mailmind_gmail_oauth_state"
GMAIL_OAUTH_PROVIDER = "gmail"
GMAIL_COMPOSE_OAUTH_PROVIDER = "gmail_compose"
GMAIL_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_STATE_TTL_SECONDS = 600


def _delete_state_cookie(response: Response) -> None:
    response.delete_cookie(
        GMAIL_STATE_COOKIE_NAME,
        path="/api/integrations/gmail/callback",
        secure=get_cookie_secure(),
        httponly=True,
        samesite=get_cookie_samesite(),
    )


def _gmail_redirect(
    *,
    connected: bool = False,
    compose_enabled: bool = False,
    error: str | None = None,
) -> RedirectResponse:
    target = f"{get_frontend_url()}/settings"
    if connected:
        target += "?gmail=compose_connected" if compose_enabled else "?gmail=connected"
    elif error:
        target += f"?gmail_error={error}"
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    _delete_state_cookie(response)
    return response


@router.get("/status", response_model=GmailStatusRead)
def gmail_connection_status(
    session: DatabaseSession, user: CurrentUser
) -> GmailStatusRead:
    return GmailStatusRead(**gmail_status(session, user))


@router.post("/connect", response_model=GmailConnectRead)
def gmail_connect(
    response: Response,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> GmailConnectRead:
    try:
        config = get_gmail_oauth_config()
        state, _, challenge = create_oauth_transaction(
            session, provider=GMAIL_OAUTH_PROVIDER, user_id=user.id
        )
    except ConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gmail integration is not configured",
        ) from error

    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": f"openid email profile {GMAIL_READONLY_SCOPE}",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent select_account",
        "include_granted_scopes": "false",
    }
    authorization_url = f"{GMAIL_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"
    response.set_cookie(
        GMAIL_STATE_COOKIE_NAME,
        state,
        max_age=GMAIL_STATE_TTL_SECONDS,
        path="/api/integrations/gmail/callback",
        secure=get_cookie_secure(),
        httponly=True,
        samesite=get_cookie_samesite(),
    )
    return GmailConnectRead(authorization_url=authorization_url)


@router.post("/compose/connect", response_model=GmailConnectRead)
def gmail_compose_connect(
    response: Response,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> GmailConnectRead:
    try:
        config = get_gmail_oauth_config()
        account = require_gmail_account(session, user)
        if GMAIL_COMPOSE_SCOPE in (account.granted_scopes or []):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Gmail compose permission is already connected",
            )
        state, _, challenge = create_oauth_transaction(
            session, provider=GMAIL_COMPOSE_OAUTH_PROVIDER, user_id=user.id
        )
    except GmailNotConnected as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect Gmail before enabling draft and send access",
        ) from error
    except GmailReauthorizationRequired as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reconnect Gmail before enabling draft and send access",
        ) from error
    except ConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gmail integration is not configured",
        ) from error

    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": f"openid email profile {GMAIL_READONLY_SCOPE} {GMAIL_COMPOSE_SCOPE}",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent select_account",
        "include_granted_scopes": "true",
    }
    authorization_url = f"{GMAIL_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"
    response.set_cookie(
        GMAIL_STATE_COOKIE_NAME,
        state,
        max_age=GMAIL_STATE_TTL_SECONDS,
        path="/api/integrations/gmail/callback",
        secure=get_cookie_secure(),
        httponly=True,
        samesite=get_cookie_samesite(),
    )
    return GmailConnectRead(authorization_url=authorization_url)


@router.get("/callback")
def gmail_callback(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    state: Annotated[str | None, Query(max_length=128)] = None,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=100)] = None,
) -> RedirectResponse:
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state is required",
        )
    oauth_provider = session.scalar(
        select(OAuthTransaction.provider).where(
            OAuthTransaction.state_hash == token_digest(state)
        )
    )
    if oauth_provider not in {
        GMAIL_OAUTH_PROVIDER,
        GMAIL_COMPOSE_OAUTH_PROVIDER,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state validation failed",
        )
    required_provider_scope = (
        GMAIL_COMPOSE_SCOPE
        if oauth_provider == GMAIL_COMPOSE_OAUTH_PROVIDER
        else None
    )
    try:
        verifier = consume_oauth_transaction(
            session,
            state,
            request.cookies.get(GMAIL_STATE_COOKIE_NAME),
            provider=oauth_provider,
            user_id=user.id,
            require_bound_user=True,
        )
    except OAuthStateError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state validation failed",
        ) from error

    if error:
        return _gmail_redirect(
            error="cancelled" if error == "access_denied" else "provider_error"
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth authorization code is required",
        )

    try:
        config = get_gmail_oauth_config()
        token_response = exchange_google_token_response(code, verifier, config)
        identity_token = token_response.get("id_token")
        access_token = token_response.get("access_token")
        expires_in = token_response.get("expires_in")
        granted_scopes = token_response.get("scope")
        if (
            not isinstance(identity_token, str)
            or not isinstance(access_token, str)
            or not access_token
            or not isinstance(expires_in, (int, float))
            or isinstance(expires_in, bool)
            or not 1 <= expires_in <= 86400
            or not isinstance(granted_scopes, str)
            or GMAIL_READONLY_SCOPE not in granted_scopes.split()
            or (
                required_provider_scope is not None
                and required_provider_scope not in granted_scopes.split()
            )
        ):
            raise GoogleOAuthError

        identity = verify_google_identity(identity_token, config.client_id)
        subject = identity.get("sub")
        identity_email = identity.get("email")
        if (
            not isinstance(subject, str)
            or not isinstance(identity_email, str)
            or identity.get("email_verified") is not True
        ):
            raise GoogleIdentityError

        login_identity = session.scalar(
            select(ConnectedAccount).where(
                ConnectedAccount.user_id == user.id,
                ConnectedAccount.provider == "google",
            )
        )
        if login_identity is None or login_identity.provider_account_id != subject:
            raise GoogleIdentityError

        account = session.scalar(
            select(ConnectedAccount).where(
                ConnectedAccount.provider == GMAIL_PROVIDER,
                ConnectedAccount.provider_account_id == subject,
            )
        )
        if account is not None and account.user_id != user.id:
            raise GoogleIdentityError
        user_gmail_account = session.scalar(
            select(ConnectedAccount).where(
                ConnectedAccount.user_id == user.id,
                ConnectedAccount.provider == GMAIL_PROVIDER,
            )
        )
        if user_gmail_account is not None:
            if (
                user_gmail_account.provider_account_id != subject
                or (account is not None and user_gmail_account.id != account.id)
            ):
                raise GoogleIdentityError
            account = user_gmail_account
        elif account is None:
            account = ConnectedAccount(
                user_id=user.id,
                provider=GMAIL_PROVIDER,
                provider_account_id=subject,
                status="pending",
            )
            session.add(account)
            session.flush()

        refresh_token = token_response.get("refresh_token")
        if isinstance(refresh_token, str) and refresh_token:
            encrypted_refresh_token = encrypt_token(
                refresh_token, account.id, "refresh"
            )
        elif account.refresh_token_encrypted:
            encrypted_refresh_token = account.refresh_token_encrypted
        else:
            raise GoogleOAuthError
        account.email_address = identity_email.strip().lower()[:320]
        account.access_token_encrypted = encrypt_token(
            access_token, account.id, "access"
        )
        account.refresh_token_encrypted = encrypted_refresh_token
        account.token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(expires_in)
        )
        account.granted_scopes = granted_scopes.split()
        account.status = "connected"
        session.commit()
    except (
        ConfigurationError,
        GoogleOAuthError,
        GoogleIdentityError,
        ValueError,
    ) as exception:
        session.rollback()
        logger.warning(
            "Gmail authorization rejected (%s)", type(exception).__name__
        )
        return _gmail_redirect(error="authorization_failed")
    except SQLAlchemyError as exception:
        session.rollback()
        logger.error("Gmail persistence failed (%s)", type(exception).__name__)
        return _gmail_redirect(error="authorization_failed")

    return _gmail_redirect(
        connected=True,
        compose_enabled=oauth_provider == GMAIL_COMPOSE_OAUTH_PROVIDER,
    )


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def gmail_disconnect(
    session: DatabaseSession, user: CsrfProtectedUser
) -> Response:
    disconnect_gmail(session, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sync", response_model=GmailSyncRead)
def gmail_sync(
    session: DatabaseSession,
    user: CsrfProtectedUser,
    max_messages: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> GmailSyncRead:
    try:
        account = require_gmail_account(session, user)
        result = sync_gmail(session, user, account, limit=max_messages)
    except GmailNotConnected as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect Gmail before synchronizing",
        ) from error
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
    except GmailAPINotEnabled as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Gmail API is not enabled in your Google Cloud project. Please enable it in Google Cloud Console and try again.",
        ) from error
    except (GmailAPIUnavailable, ConfigurationError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gmail synchronization failed",
        ) from error
    return GmailSyncRead(**result)
