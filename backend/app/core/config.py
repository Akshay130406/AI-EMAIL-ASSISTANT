import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class ConfigurationError(RuntimeError):
    pass


class TokenEncryptionConfigurationError(ConfigurationError):
    pass


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class GmailOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class CalendarOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


def get_app_env() -> str:
    return os.getenv("APP_ENV", "production").strip().lower()


def get_cors_origins() -> list[str]:
    configured_origins = os.getenv(
        "ALLOWED_ORIGINS",
        os.getenv("CORS_ORIGINS", "http://localhost:5174,http://127.0.0.1:5174"),
    )
    return [
        origin.strip().rstrip("/")
        for origin in configured_origins.split(",")
        if origin.strip()
    ]


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def get_frontend_url() -> str:
    value = os.getenv("FRONTEND_URL", "http://localhost:5174").strip().rstrip("/")
    parsed = urlparse(value)
    local_http = (
        get_app_env() == "development"
        and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1"}
    )
    if (
        parsed.scheme != "https" and not local_http
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError("FRONTEND_URL must be a trusted HTTPS origin")
    return value


def get_session_secret() -> str:
    secret = os.getenv("SESSION_SECRET", "").strip()
    if len(secret) < 32:
        raise ConfigurationError("SESSION_SECRET must contain at least 32 characters")
    return secret


def get_cookie_secure() -> bool:
    configured = os.getenv("COOKIE_SECURE")
    if configured is None:
        return get_app_env() != "development"
    return configured.strip().lower() in {"1", "true", "yes"}


def get_cookie_samesite() -> str:
    return os.getenv(
        "COOKIE_SAMESITE", "lax" if get_app_env() == "development" else "none"
    ).strip().lower()


def get_google_oauth_config() -> GoogleOAuthConfig:
    values = {
        "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        "GOOGLE_CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        "GOOGLE_REDIRECT_URI": os.getenv("GOOGLE_REDIRECT_URI", "").strip(),
    }
    if any(
        not value or value.lower().startswith("replace-with")
        for value in values.values()
    ):
        raise ConfigurationError("Google OAuth configuration is incomplete")
    return GoogleOAuthConfig(
        client_id=values["GOOGLE_CLIENT_ID"],
        client_secret=values["GOOGLE_CLIENT_SECRET"],
        redirect_uri=values["GOOGLE_REDIRECT_URI"],
    )


def get_gmail_oauth_config() -> GmailOAuthConfig:
    config = get_google_oauth_config()
    redirect_uri = os.getenv("GMAIL_REDIRECT_URI", "").strip()
    if not redirect_uri or redirect_uri.lower().startswith("replace-with"):
        raise ConfigurationError("Gmail OAuth redirect URI is not configured")
    return GmailOAuthConfig(
        client_id=config.client_id,
        client_secret=config.client_secret,
        redirect_uri=redirect_uri,
    )


def get_calendar_oauth_config() -> CalendarOAuthConfig:
    config = get_google_oauth_config()
    redirect_uri = os.getenv("CALENDAR_REDIRECT_URI", "").strip()
    if not redirect_uri or redirect_uri.lower().startswith("replace-with"):
        raise ConfigurationError("Calendar OAuth redirect URI is not configured")
    return CalendarOAuthConfig(
        client_id=config.client_id,
        client_secret=config.client_secret,
        redirect_uri=redirect_uri,
    )


def get_token_encryption_keys() -> tuple[str, dict[str, bytes]]:
    import base64
    import binascii

    current_id = os.getenv("TOKEN_ENCRYPTION_KEY_ID", "current").strip()
    current_value = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    previous_values = os.getenv("TOKEN_ENCRYPTION_KEY_PREVIOUS", "").strip()
    if not current_id or not current_value:
        raise TokenEncryptionConfigurationError(
            "Gmail token encryption is not configured"
        )
    encoded_keys = [f"{current_id}:{current_value}"]
    if previous_values:
        encoded_keys.extend(item.strip() for item in previous_values.split(",") if item.strip())

    keys: dict[str, bytes] = {}
    for item in encoded_keys:
        key_id, separator, encoded_key = item.partition(":")
        if not separator or not key_id or key_id in keys:
            raise TokenEncryptionConfigurationError(
                "Gmail token encryption keys are invalid"
            )
        try:
            decoded = base64.b64decode(
                encoded_key.encode("ascii"), altchars=b"-_", validate=True
            )
        except (UnicodeEncodeError, binascii.Error) as error:
            raise TokenEncryptionConfigurationError(
                "Gmail token encryption key must be base64-encoded"
            ) from error
        if len(decoded) != 32:
            raise TokenEncryptionConfigurationError(
                "Gmail token encryption keys must decode to 32 bytes"
            )
        keys[key_id] = decoded
    if current_id not in keys:
        raise TokenEncryptionConfigurationError(
            "Current Gmail token encryption key is unavailable"
        )
    return current_id, keys


def get_gmail_sync_limit() -> int:
    value = os.getenv("GMAIL_SYNC_MAX_MESSAGES", "50").strip()
    try:
        limit = int(value)
    except ValueError as error:
        raise ConfigurationError("GMAIL_SYNC_MAX_MESSAGES must be an integer") from error
    if not 1 <= limit <= 100:
        raise ConfigurationError("GMAIL_SYNC_MAX_MESSAGES must be between 1 and 100")
    return limit


def get_gemini_config() -> tuple[str, str, int, int, int, int]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    try:
        timeout = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "25"))
        output_tokens = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "1200"))
        input_chars = int(os.getenv("GEMINI_MAX_INPUT_CHARS", "16000"))
        requests_per_minute = int(os.getenv("AI_USER_REQUESTS_PER_MINUTE", "12"))
    except ValueError as error:
        raise ConfigurationError("Gemini limits must be integers") from error
    if not model or not 1 <= timeout <= 120:
        raise ConfigurationError("Gemini model and timeout configuration are invalid")
    if not 128 <= output_tokens <= 8192:
        raise ConfigurationError("GEMINI_MAX_OUTPUT_TOKENS must be between 128 and 8192")
    if not 1000 <= input_chars <= 100000:
        raise ConfigurationError("GEMINI_MAX_INPUT_CHARS must be between 1000 and 100000")
    if not 1 <= requests_per_minute <= 120:
        raise ConfigurationError("AI_USER_REQUESTS_PER_MINUTE must be between 1 and 120")
    return api_key, model, timeout, output_tokens, input_chars, requests_per_minute


def validate_production_config() -> None:
    if get_app_env() == "development":
        return

    required = ("DATABASE_URL", "FRONTEND_URL", "BACKEND_URL")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise ConfigurationError(
            "Required production configuration is missing: " + ", ".join(missing)
        )

    oauth = get_google_oauth_config()
    gmail_oauth = get_gmail_oauth_config()
    calendar_oauth = get_calendar_oauth_config()
    secret = get_session_secret()
    if "replace-this" in secret.lower():
        raise ConfigurationError("SESSION_SECRET must be replaced in production")
    if not get_cookie_secure() or get_cookie_samesite() != "none":
        raise ConfigurationError(
            "Production cookies require COOKIE_SECURE=true and COOKIE_SAMESITE=none"
        )

    frontend = get_frontend_url()
    backend = os.getenv("BACKEND_URL", "").strip().rstrip("/")
    origins = get_cors_origins()
    parsed_frontend = urlparse(frontend)
    parsed_backend = urlparse(backend)
    if "*" in origins:
        raise ConfigurationError("Wildcard origins are not allowed in production")
    if frontend not in origins:
        raise ConfigurationError("FRONTEND_URL must be included in ALLOWED_ORIGINS")
    if (
        parsed_frontend.scheme != "https"
        or not parsed_frontend.netloc
        or parsed_frontend.path
        or parsed_frontend.query
        or parsed_frontend.fragment
        or parsed_backend.scheme != "https"
        or not parsed_backend.netloc
        or parsed_backend.path
        or parsed_backend.query
        or parsed_backend.fragment
    ):
        raise ConfigurationError("Production frontend and backend URLs must use HTTPS")
    if any(
        urlparse(origin).scheme != "https"
        or not urlparse(origin).netloc
        or urlparse(origin).path
        or urlparse(origin).query
        or urlparse(origin).fragment
        for origin in origins
    ):
        raise ConfigurationError("Production allowed origins must be HTTPS origins")
    if oauth.redirect_uri != f"{backend}/api/auth/google/callback":
        raise ConfigurationError(
            "GOOGLE_REDIRECT_URI must match the backend OAuth callback URL"
        )
    if gmail_oauth.redirect_uri != f"{backend}/api/integrations/gmail/callback":
        raise ConfigurationError(
            "GMAIL_REDIRECT_URI must match the Gmail authorization callback URL"
        )
    if calendar_oauth.redirect_uri != f"{backend}/api/integrations/calendar/callback":
        raise ConfigurationError(
            "CALENDAR_REDIRECT_URI must match the Calendar authorization callback URL"
        )
    get_token_encryption_keys()
    database_url = get_database_url()
    if urlparse(database_url).scheme not in {
        "postgres",
        "postgresql",
        "postgresql+psycopg",
    }:
        raise ConfigurationError(
            "Production DATABASE_URL must use PostgreSQL"
        )


def validate_runtime_config() -> None:
    if get_cookie_samesite() not in {"lax", "strict", "none"}:
        raise ConfigurationError("COOKIE_SAMESITE must be lax, strict, or none")
    if get_cookie_samesite() == "none" and not get_cookie_secure():
        raise ConfigurationError("SameSite=None cookies require COOKIE_SECURE=true")
    origins = get_cors_origins()
    if "*" in origins:
        raise ConfigurationError("Wildcard CORS origins are not allowed")
    for origin in origins:
        parsed = urlparse(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigurationError("ALLOWED_ORIGINS must contain only explicit origins")
    get_gmail_sync_limit()
    get_gemini_config()
