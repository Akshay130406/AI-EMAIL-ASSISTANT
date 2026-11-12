import httpx
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from app.core.config import CalendarOAuthConfig, GmailOAuthConfig, GoogleOAuthConfig
from app.services.auth import GoogleIdentityError

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class GoogleOAuthError(Exception):
    pass


def exchange_google_token_response(
    code: str,
    verifier: str,
    config: GoogleOAuthConfig | GmailOAuthConfig | CalendarOAuthConfig,
) -> dict[str, object]:
    try:
        response = httpx.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": config.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=10,
        )
        response.raise_for_status()
        token_response = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise GoogleOAuthError from error

    if not isinstance(token_response, dict):
        raise GoogleOAuthError
    return token_response


def exchange_google_code(
    code: str,
    verifier: str,
    config: GoogleOAuthConfig | GmailOAuthConfig | CalendarOAuthConfig,
) -> str:
    token_response = exchange_google_token_response(code, verifier, config)
    identity_token = token_response.get("id_token")
    if not isinstance(identity_token, str) or not identity_token:
        raise GoogleOAuthError
    return identity_token


def verify_google_identity(identity_token: str, client_id: str) -> dict[str, object]:
    try:
        claims = id_token.verify_oauth2_token(
            identity_token, GoogleRequest(), audience=client_id
        )
    except Exception as error:
        raise GoogleIdentityError from error
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise GoogleIdentityError
    return claims
