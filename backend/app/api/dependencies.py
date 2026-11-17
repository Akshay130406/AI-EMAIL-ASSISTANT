import hmac
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import ConfigurationError, get_cors_origins
from app.database.session import get_db
from app.models import User, UserSession
from app.services.auth import find_active_session, token_digest

SESSION_COOKIE_NAME = "mailmind_session"
logger = logging.getLogger(__name__)


def get_current_auth_session(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
) -> UserSession:
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    try:
        auth_session = find_active_session(session, session_token)
    except ConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        ) from error
    if auth_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return auth_session


def get_current_user(
    auth_session: Annotated[UserSession, Depends(get_current_auth_session)],
    session: Annotated[Session, Depends(get_db)],
) -> User:
    user = session.get(User, auth_session.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def require_csrf(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    auth_session: Annotated[UserSession, Depends(get_current_auth_session)],
) -> User:
    origin = request.headers.get("origin", "").rstrip("/")
    csrf_token = request.headers.get("x-csrf-token", "")
    allowed_origins = get_cors_origins()
    if not origin:
        logger.warning("CSRF validation rejected request (missing_origin)")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )
    if origin not in allowed_origins:
        logger.warning("CSRF validation rejected request (origin_not_allowed)")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )
    if not csrf_token:
        logger.warning("CSRF validation rejected request (missing_token)")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )
    try:
        valid_token = hmac.compare_digest(
            token_digest(csrf_token), auth_session.csrf_token_hash
        )
    except ConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        ) from error
    if not valid_token:
        logger.warning("CSRF validation rejected request (token_mismatch)")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )
    return user


CurrentAuthSession = Annotated[UserSession, Depends(get_current_auth_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CsrfProtectedUser = Annotated[User, Depends(require_csrf)]
DatabaseSession = Annotated[Session, Depends(get_db)]
