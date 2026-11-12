import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_session_secret
from app.models import ConnectedAccount, OAuthTransaction, User, UserSession

OAUTH_FLOW_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=7)
GOOGLE_PROVIDER = "google"


class OAuthStateError(Exception):
    pass


class GoogleIdentityError(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def token_digest(value: str) -> str:
    return hmac.new(
        get_session_secret().encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def derive_csrf_token(session_token: str) -> str:
    return hmac.new(
        get_session_secret().encode("utf-8"),
        f"csrf:{session_token}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_oauth_transaction(
    session: Session,
    *,
    provider: str = "google_login",
    user_id=None,
) -> tuple[str, str, str]:
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    session.execute(
        delete(OAuthTransaction).where(OAuthTransaction.expires_at <= _utcnow())
    )
    session.add(
        OAuthTransaction(
            state_hash=token_digest(state),
            code_verifier=verifier,
            provider=provider,
            user_id=user_id,
            expires_at=_utcnow() + OAUTH_FLOW_TTL,
        )
    )
    session.commit()
    return state, verifier, challenge


def consume_oauth_transaction(
    session: Session,
    state: str,
    browser_state: str | None,
    *,
    provider: str = "google_login",
    user_id=None,
    require_bound_user: bool = False,
) -> str:
    if not browser_state or not hmac.compare_digest(state, browser_state) or (
        require_bound_user and user_id is None
    ):
        raise OAuthStateError
    statement = select(OAuthTransaction).where(
        OAuthTransaction.state_hash == token_digest(state),
        OAuthTransaction.provider == provider,
    )
    if require_bound_user:
        statement = statement.where(OAuthTransaction.user_id == user_id)
    else:
        statement = statement.where(OAuthTransaction.user_id == user_id)
    transaction = session.scalar(statement)
    if transaction is None or _aware(transaction.expires_at) <= _utcnow():
        if transaction is not None:
            session.delete(transaction)
            session.commit()
        raise OAuthStateError
    verifier = transaction.code_verifier
    session.delete(transaction)
    session.commit()
    return verifier


def create_or_link_google_user(session: Session, identity: dict[str, object]) -> User:
    subject = identity.get("sub")
    email = identity.get("email")
    verified = identity.get("email_verified")
    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(email, str)
        or not email
        or verified is not True
    ):
        raise GoogleIdentityError

    normalized_email = email.strip().lower()
    account = session.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.provider == GOOGLE_PROVIDER,
            ConnectedAccount.provider_account_id == subject,
        )
    )
    if account is not None:
        user = session.get(User, account.user_id)
        if user is None:
            raise GoogleIdentityError
        account.status = "connected"
        _update_user_profile(user, identity)
        session.commit()
        return user

    user = session.scalar(select(User).where(User.email == normalized_email))
    if user is not None:
        existing_google_account = session.scalar(
            select(ConnectedAccount).where(
                ConnectedAccount.user_id == user.id,
                ConnectedAccount.provider == GOOGLE_PROVIDER,
            )
        )
        if existing_google_account is not None:
            raise GoogleIdentityError
    else:
        name = identity.get("name")
        user = User(
            email=normalized_email,
            display_name=name if isinstance(name, str) else None,
            profile={},
        )
        session.add(user)
        session.flush()

    _update_user_profile(user, identity)
    session.add(
        ConnectedAccount(
            user_id=user.id,
            provider=GOOGLE_PROVIDER,
            provider_account_id=subject,
            status="connected",
        )
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        linked_account = session.scalar(
            select(ConnectedAccount).where(
                ConnectedAccount.provider == GOOGLE_PROVIDER,
                ConnectedAccount.provider_account_id == subject,
            )
        )
        if linked_account is not None:
            linked_user = session.get(User, linked_account.user_id)
            if linked_user is not None:
                return linked_user
        raise GoogleIdentityError from error
    return user


def _update_user_profile(user: User, identity: dict[str, object]) -> None:
    name = identity.get("name")
    picture = identity.get("picture")
    if isinstance(name, str) and name.strip():
        user.display_name = name.strip()[:120]
    profile = dict(user.profile or {})
    if isinstance(picture, str) and picture.startswith("https://"):
        profile["picture_url"] = picture[:2048]
    user.profile = profile


def create_user_session(
    session: Session, user: User, previous_session_token: str | None = None
) -> tuple[str, str, UserSession]:
    if previous_session_token:
        old_session = session.scalar(
            select(UserSession).where(
                UserSession.session_token_hash == token_digest(previous_session_token)
            )
        )
        if old_session is not None:
            session.delete(old_session)

    session_token = secrets.token_urlsafe(32)
    csrf_token = derive_csrf_token(session_token)
    auth_session = UserSession(
        user_id=user.id,
        session_token_hash=token_digest(session_token),
        csrf_token_hash=token_digest(csrf_token),
        expires_at=_utcnow() + SESSION_TTL,
    )
    session.add(auth_session)
    session.commit()
    return session_token, csrf_token, auth_session


def find_active_session(session: Session, session_token: str) -> UserSession | None:
    return session.scalar(
        select(UserSession).where(
            UserSession.session_token_hash == token_digest(session_token),
            UserSession.expires_at > _utcnow(),
        )
    )


def revoke_session(session: Session, auth_session: UserSession) -> None:
    session.delete(auth_session)
    session.commit()
