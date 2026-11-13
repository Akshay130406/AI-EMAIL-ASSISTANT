import logging
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.dependencies import (
    CurrentAuthSession,
    CurrentUser,
    SESSION_COOKIE_NAME,
    require_csrf,
)
from app.core.config import (
    ConfigurationError,
    get_cookie_samesite,
    get_cookie_secure,
    get_frontend_url,
    get_google_oauth_config,
)
from app.database.session import get_db
from app.models import User
from app.schemas.auth import AuthMeRead, AuthenticatedUserRead
from app.services.auth import (
    GoogleIdentityError,
    OAuthStateError,
    consume_oauth_transaction,
    create_oauth_transaction,
    create_or_link_google_user,
    create_user_session,
    derive_csrf_token,
    revoke_session,
)
from app.services.google_oauth import (
    GoogleOAuthError,
    exchange_google_code,
    verify_google_identity,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger(__name__)
OAUTH_STATE_COOKIE_NAME = "mailmind_oauth_state"
OAUTH_STATE_TTL_SECONDS = 600
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_SCOPES = "openid email profile"


def _delete_oauth_cookie(response: Response) -> None:
    response.delete_cookie(
        OAUTH_STATE_COOKIE_NAME,
        path="/api/auth/google/callback",
        secure=get_cookie_secure(),
        httponly=True,
        samesite=get_cookie_samesite(),
    )


def _login_error_redirect(error: str) -> RedirectResponse:
    response = RedirectResponse(
        f"{get_frontend_url()}/login?auth_error={error}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _delete_oauth_cookie(response)
    return response


@router.get("/google")
def google_login(session: Session = Depends(get_db)) -> RedirectResponse:
    try:
        config = get_google_oauth_config()
    except ConfigurationError:
        return _login_error_redirect("not_configured")

    try:
        state, _, challenge = create_oauth_transaction(session)
    except ConfigurationError:
        return _login_error_redirect("not_configured")
    authorization_parameters = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorization_url = (
        f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(authorization_parameters)}"
    )
    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        state,
        max_age=OAUTH_STATE_TTL_SECONDS,
        path="/api/auth/google/callback",
        secure=get_cookie_secure(),
        httponly=True,
        samesite=get_cookie_samesite(),
    )
    return response


@router.get("/google/callback")
def google_callback(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    state: Annotated[str | None, Query(max_length=128)] = None,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=100)] = None,
) -> RedirectResponse:
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state is required",
        )
    try:
        verifier = consume_oauth_transaction(
            session, state, request.cookies.get(OAUTH_STATE_COOKIE_NAME)
        )
    except OAuthStateError as state_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state validation failed",
        ) from state_error

    if error:
        return _login_error_redirect(
            "cancelled" if error == "access_denied" else "provider_error"
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth authorization code is required",
        )
    try:
        config = get_google_oauth_config()
        identity_token = exchange_google_code(code, verifier, config)
        identity = verify_google_identity(identity_token, config.client_id)
        user = create_or_link_google_user(session, identity)
        previous_session = request.cookies.get(SESSION_COOKIE_NAME)
        session_token, _, _ = create_user_session(session, user, previous_session)
    except (ConfigurationError, GoogleOAuthError, GoogleIdentityError) as error:
        logger.warning("Google OAuth callback rejected (%s)", type(error).__name__)
        return _login_error_redirect("sign_in_failed")

    response = RedirectResponse(
        get_frontend_url(), status_code=status.HTTP_303_SEE_OTHER
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        max_age=SESSION_TTL_SECONDS,
        path="/",
        secure=get_cookie_secure(),
        httponly=True,
        samesite=get_cookie_samesite(),
    )
    _delete_oauth_cookie(response)
    return response


@router.get("/me", response_model=AuthMeRead)
def auth_me(
    request: Request,
    user: CurrentUser,
) -> AuthMeRead:
    profile = user.profile or {}
    picture = profile.get("picture_url")
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return AuthMeRead(
        user=AuthenticatedUserRead(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            picture_url=picture if isinstance(picture, str) else None,
        ),
        csrf_token=derive_csrf_token(session_token),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, Depends(require_csrf)],
    auth_session: CurrentAuthSession,
) -> None:
    revoke_session(session, auth_session)
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=get_cookie_secure(),
        httponly=True,
        samesite=get_cookie_samesite(),
    )
