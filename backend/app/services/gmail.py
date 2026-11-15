import base64
import json
import logging
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Protocol
from uuid import UUID

import bleach
import httplib2
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.discovery import Resource
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import (
    ConfigurationError,
    TokenEncryptionConfigurationError,
    get_google_oauth_config,
    get_gmail_sync_limit,
)
from app.models import ConnectedAccount, Draft, Email, User
from app.services.token_encryption import (
    TokenDecryptionError,
    decrypt_token,
    encrypt_token,
    uses_current_key,
)

logger = logging.getLogger(__name__)
GMAIL_PROVIDER = "gmail"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
HTML_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "caption", "code", "div", "em",
    "h1", "h2", "h3", "h4", "hr", "i", "li", "ol", "p", "pre", "span",
    "strong", "table", "tbody", "td", "th", "thead", "tr", "u", "ul",
}
HTML_ATTRIBUTES = {"a": ["href", "title"]}
SKIP_TAGS = {"script", "style", "head"}


class GmailError(Exception):
    pass


class GmailNotConnected(GmailError):
    pass


class GmailReauthorizationRequired(GmailError):
    pass


class GmailAPIUnavailable(GmailError):
    pass


class GmailAPINotEnabled(GmailAPIUnavailable):
    pass


class GmailRateLimited(GmailAPIUnavailable):
    pass


class GmailHistoryExpired(GmailAPIUnavailable):
    pass


class GmailWriteRejected(GmailError):
    pass


class GmailWriteOutcomeUnknown(GmailAPIUnavailable):
    pass


class ResourceRequest(Protocol):
    def execute(self, num_retries: int = 0) -> dict[str, object]: ...


def _google_error_reasons(error: HttpError) -> set[str]:
    try:
        payload = json.loads(error.content)
    except (TypeError, ValueError):
        return set()
    details = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(details, dict):
        return set()
    reasons: set[str] = set()
    for key in ("errors", "details"):
        entries = details.get(key)
        if isinstance(entries, list):
            reasons.update(
                item["reason"]
                for item in entries
                if isinstance(item, dict) and isinstance(item.get("reason"), str)
            )
    return reasons


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in SKIP_TAGS:
            self.skip_depth += 1
        elif tag in {"br", "p", "div", "li", "tr"} and self.skip_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif tag in {"p", "div", "li", "tr"} and self.skip_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(data)


def sanitize_html(value: str) -> str:
    return bleach.clean(
        value,
        tags=HTML_TAGS,
        attributes=HTML_ATTRIBUTES,
        protocols={"http", "https", "mailto"},
        strip=True,
        strip_comments=True,
    )


def decode_body_data(value: str) -> str:
    if not isinstance(value, str):
        return ""
    try:
        encoded = value.encode("ascii")
        decoded = base64.urlsafe_b64decode(
            encoded + b"=" * (-len(encoded) % 4)
        )
        return decoded.decode("utf-8", errors="replace")
    except (UnicodeEncodeError, ValueError):
        return ""


def _decoded_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeDecodeError, ValueError):
        return value


def _header(headers: list[dict[str, object]], name: str) -> str:
    target = name.lower()
    for item in headers:
        key = item.get("name")
        value = item.get("value")
        if isinstance(key, str) and key.lower() == target and isinstance(value, str):
            return _decoded_header(value)
    return ""


def _addresses(value: str) -> list[str]:
    result: list[str] = []
    for name, address in getaddresses([value]):
        if not address or "@" not in address or "\r" in address or "\n" in address:
            continue
        result.append(formataddr((_decoded_header(name), address)) if name else address)
    return result


def _mailbox_addresses(value: str) -> list[str]:
    return [
        address
        for _, address in getaddresses([value])
        if address
        and "@" in address
        and "\r" not in address
        and "\n" not in address
    ]


def _extract_mime_bodies(payload: dict[str, object]) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    pending = [payload]
    while pending:
        part = pending.pop()
        mime_type = part.get("mimeType")
        filename = part.get("filename")
        if isinstance(filename, str) and filename:
            continue
        children = part.get("parts")
        if isinstance(children, list):
            pending.extend(child for child in children if isinstance(child, dict))
        body = part.get("body")
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, str):
            continue
        decoded = decode_body_data(data)
        if mime_type == "text/plain":
            plain_parts.append(decoded)
        elif mime_type == "text/html":
            html_parts.append(decoded)

    plain = "\n".join(part for part in plain_parts if part.strip())
    raw_html = "\n".join(part for part in html_parts if part.strip())
    sanitized_html = sanitize_html(raw_html) if raw_html else ""
    if not plain and raw_html:
        parser = _TextExtractor()
        parser.feed(raw_html)
        parser.close()
        plain = "".join(parser.parts)
    return plain.strip(), sanitized_html


def parse_gmail_message(message: dict[str, object]) -> dict[str, object]:
    payload = message.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    headers = payload.get("headers")
    if not isinstance(headers, list):
        headers = []
    headers = [header for header in headers if isinstance(header, dict)]
    sender_header = _header(headers, "From")
    sender_name, sender_address = getaddresses([sender_header])[0] if sender_header else ("", "")
    sender = (
        formataddr((_decoded_header(sender_name), sender_address))
        if sender_address
        else sender_header[:320]
    )
    recipients = _addresses(
        ", ".join(filter(None, (_header(headers, "To"), _header(headers, "Cc"))))
    )
    body, html_body = _extract_mime_bodies(payload)
    labels = message.get("labelIds")
    label_ids = {label for label in labels if isinstance(label, str)} if isinstance(labels, list) else set()
    received_at = None
    internal_date = message.get("internalDate")
    if isinstance(internal_date, str) and internal_date.isdigit():
        try:
            received_at = datetime.fromtimestamp(
                int(internal_date) / 1000, tz=timezone.utc
            )
        except (OverflowError, OSError, ValueError):
            received_at = None
    if received_at is None:
        date_header = _header(headers, "Date")
        if date_header:
            try:
                received_at = parsedate_to_datetime(date_header)
                if received_at.tzinfo is None:
                    received_at = received_at.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                received_at = None
    message_id = message.get("id")
    thread_id = message.get("threadId")
    snippet = message.get("snippet")
    preview = " ".join((body or (snippet if isinstance(snippet, str) else "")).split())[:500]
    return {
        "external_message_id": message_id if isinstance(message_id, str) else None,
        "thread_id": thread_id if isinstance(thread_id, str) else None,
        "sender": sender or "Unknown sender",
        "recipients": recipients,
        "subject": _header(headers, "Subject")[:998],
        "body": body or (snippet if isinstance(snippet, str) else ""),
        "html_body": html_body or None,
        "preview": preview or None,
        "is_read": "UNREAD" not in label_ids,
        "is_sent": "SENT" in label_ids,
        "is_starred": "STARRED" in label_ids,
        "is_priority": "IMPORTANT" in label_ids,
        "received_at": received_at,
    }


def get_gmail_account(session: Session, user: User) -> ConnectedAccount | None:
    return session.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.user_id == user.id,
            ConnectedAccount.provider == GMAIL_PROVIDER,
        )
    )


def require_gmail_account(session: Session, user: User) -> ConnectedAccount:
    account = get_gmail_account(session, user)
    if account is None:
        raise GmailNotConnected
    if account.status != "connected":
        raise GmailReauthorizationRequired
    if not account.access_token_encrypted:
        raise GmailReauthorizationRequired
    return account


def require_gmail_compose_account(
    session: Session, user: User
) -> ConnectedAccount:
    account = require_gmail_account(session, user)
    if GMAIL_COMPOSE_SCOPE not in (account.granted_scopes or []):
        raise GmailReauthorizationRequired
    return account


def _mark_reauthorization_required(session: Session, account: ConnectedAccount) -> None:
    account.status = "disconnected"
    account.access_token_encrypted = None
    account.refresh_token_encrypted = None
    account.token_expires_at = None
    session.commit()


def _credentials_for_account(
    session: Session, account: ConnectedAccount
) -> Credentials:
    locked_account = session.scalar(
        select(ConnectedAccount)
        .where(
            ConnectedAccount.id == account.id,
            ConnectedAccount.provider == GMAIL_PROVIDER,
        )
        .with_for_update()
    )
    if locked_account is None or locked_account.status != "connected":
        raise GmailReauthorizationRequired
    account = locked_account
    if not account.access_token_encrypted:
        _mark_reauthorization_required(session, account)
        raise GmailReauthorizationRequired
    config = get_google_oauth_config()
    try:
        access_token = decrypt_token(
            account.access_token_encrypted, account.id, "access"
        )
        refresh_token = (
            decrypt_token(account.refresh_token_encrypted, account.id, "refresh")
            if account.refresh_token_encrypted
            else None
        )
    except TokenEncryptionConfigurationError as error:
        logger.error("Gmail token encryption configuration is invalid")
        raise GmailAPIUnavailable from error
    except TokenDecryptionError as error:
        logger.error("Gmail credential decryption failed (%s)", type(error).__name__)
        raise GmailAPIUnavailable from error

    if not uses_current_key(account.access_token_encrypted) or (
        account.refresh_token_encrypted
        and not uses_current_key(account.refresh_token_encrypted)
    ):
        account.access_token_encrypted = encrypt_token(
            access_token, account.id, "access"
        )
        if refresh_token:
            account.refresh_token_encrypted = encrypt_token(
                refresh_token, account.id, "refresh"
            )
        session.commit()

    expiry = account.token_expires_at
    if expiry is not None and expiry.tzinfo is not None:
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=config.client_id,
        client_secret=config.client_secret,
        scopes=[
            scope
            for scope in (GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE)
            if scope in (account.granted_scopes or [])
        ],
        expiry=expiry,
    )

    if not credentials.valid:
        if not refresh_token:
            _mark_reauthorization_required(session, account)
            raise GmailReauthorizationRequired
        try:
            credentials.refresh(GoogleRequest())
        except RefreshError as error:
            _mark_reauthorization_required(session, account)
            logger.warning("Gmail token refresh rejected (%s)", type(error).__name__)
            raise GmailReauthorizationRequired from error
        except (GoogleAuthError, httplib2.HttpLib2Error, OSError, ValueError) as error:
            logger.warning("Gmail token refresh failed (%s)", type(error).__name__)
            raise GmailAPIUnavailable from error
        account.access_token_encrypted = encrypt_token(
            credentials.token, account.id, "access"
        )
        if credentials.refresh_token:
            account.refresh_token_encrypted = encrypt_token(
                credentials.refresh_token, account.id, "refresh"
            )
        expiry = credentials.expiry
        if expiry is not None:
            expiry = (
                expiry.replace(tzinfo=timezone.utc)
                if expiry.tzinfo is None
                else expiry.astimezone(timezone.utc)
            )
        account.token_expires_at = expiry
        account.status = "connected"
        session.commit()
    return credentials


def build_gmail_service(account: ConnectedAccount, session: Session) -> Resource:
    credentials = _credentials_for_account(session, account)
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _execute(request: ResourceRequest) -> dict[str, object]:
    try:
        result = request.execute(num_retries=2)
    except HttpError as error:
        response = getattr(error, "resp", None)
        code = getattr(response, "status", None)
        if code == 401:
            raise GmailReauthorizationRequired from error
        if code == 404:
            raise GmailHistoryExpired from error
        if code == 429:
            raise GmailRateLimited from error
        reasons = _google_error_reasons(error)
        if reasons.intersection({"accessNotConfigured"}):
            raise GmailAPINotEnabled from error
        if reasons.intersection({"authError", "insufficientPermissions"}):
            raise GmailReauthorizationRequired from error
        if reasons.intersection({"rateLimitExceeded", "userRateLimitExceeded"}):
            raise GmailRateLimited from error
        if isinstance(code, int) and code >= 500:
            raise GmailAPIUnavailable from error
        raise GmailAPIUnavailable from error
    except (GoogleAuthError, httplib2.HttpLib2Error, OSError, ValueError) as error:
        logger.warning("Gmail API request failed (%s)", type(error).__name__)
        raise GmailAPIUnavailable from error
    if not isinstance(result, dict):
        raise GmailAPIUnavailable
    return result


def _execute_write(request: ResourceRequest) -> dict[str, object]:
    try:
        result = request.execute()
    except HttpError as error:
        response = getattr(error, "resp", None)
        code = getattr(response, "status", None)
        if code == 401:
            raise GmailReauthorizationRequired from error
        if code == 429:
            raise GmailRateLimited from error
        reasons = _google_error_reasons(error)
        if reasons.intersection({"accessNotConfigured"}):
            raise GmailAPINotEnabled from error
        if reasons.intersection({"authError", "insufficientPermissions"}):
            raise GmailReauthorizationRequired from error
        if reasons.intersection({"rateLimitExceeded", "userRateLimitExceeded"}):
            raise GmailRateLimited from error
        if code == 404:
            raise GmailHistoryExpired from error
        if code in {400, 403}:
            raise GmailWriteRejected from error
        logger.warning("Gmail write outcome is uncertain (HTTP %s)", code)
        raise GmailWriteOutcomeUnknown from error
    except (GoogleAuthError, httplib2.HttpLib2Error, OSError, ValueError) as error:
        logger.warning("Gmail write outcome is uncertain (%s)", type(error).__name__)
        raise GmailWriteOutcomeUnknown from error
    if not isinstance(result, dict):
        raise GmailWriteOutcomeUnknown
    return result


def build_gmail_raw_message(
    *,
    recipients: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    body: str,
) -> str:
    message = EmailMessage(policy=policy.SMTP)
    message["To"] = ", ".join(recipients)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")


def create_remote_gmail_draft(service: Resource, raw_message: str) -> dict[str, object]:
    return _execute_write(
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw_message}})
    )


def update_remote_gmail_draft(
    service: Resource, gmail_draft_id: str, raw_message: str
) -> dict[str, object]:
    return _execute_write(
        service.users()
        .drafts()
        .update(
            userId="me",
            id=gmail_draft_id,
            body={"message": {"raw": raw_message}},
        )
    )


def get_remote_gmail_draft(
    service: Resource, gmail_draft_id: str
) -> dict[str, object]:
    return _execute(
        service.users()
        .drafts()
        .get(userId="me", id=gmail_draft_id, format="full")
    )


def list_remote_gmail_drafts(service: Resource, maximum: int) -> list[dict[str, object]]:
    response = _execute(
        service.users().drafts().list(userId="me", maxResults=maximum)
    )
    draft_refs = response.get("drafts")
    if not isinstance(draft_refs, list):
        return []
    return [
        draft
        for draft in draft_refs[:maximum]
        if isinstance(draft, dict) and isinstance(draft.get("id"), str)
    ]


def delete_remote_gmail_draft(service: Resource, gmail_draft_id: str) -> None:
    _execute_write(
        service.users().drafts().delete(userId="me", id=gmail_draft_id)
    )


def send_remote_gmail_draft(
    service: Resource, gmail_draft_id: str
) -> dict[str, object]:
    return _execute_write(
        service.users().drafts().send(userId="me", body={"id": gmail_draft_id})
    )


def parsed_gmail_draft(message: dict[str, object]) -> dict[str, object]:
    payload = message.get("payload")
    headers = payload.get("headers") if isinstance(payload, dict) else []
    headers = [header for header in headers if isinstance(header, dict)] if isinstance(headers, list) else []
    raw_to = _header(headers, "To")
    raw_cc = _header(headers, "Cc")
    raw_bcc = _header(headers, "Bcc")
    to_addresses = _mailbox_addresses(raw_to)
    cc_addresses = _mailbox_addresses(raw_cc)
    bcc_addresses = _mailbox_addresses(raw_bcc)
    body, _ = _extract_mime_bodies(payload if isinstance(payload, dict) else {})
    message_id = message.get("id")
    thread_id = message.get("threadId")
    return {
        "recipients": to_addresses,
        "cc": cc_addresses,
        "bcc": bcc_addresses,
        "recipient": ", ".join(to_addresses) or None,
        "subject": _header(headers, "Subject")[:998],
        "body": body[:100_000],
        "gmail_message_id": message_id if isinstance(message_id, str) else None,
        "gmail_thread_id": thread_id if isinstance(thread_id, str) else None,
    }


def fetch_profile(service: Resource) -> dict[str, object]:
    return _execute(service.users().getProfile(userId="me"))


def fetch_message(service: Resource, message_id: str) -> dict[str, object]:
    return _execute(
        service.users().messages().get(
            userId="me", id=message_id, format="full"
        )
    )


def fetch_thread(service: Resource, thread_id: str) -> list[dict[str, object]]:
    response = _execute(
        service.users().threads().get(
            userId="me", id=thread_id, format="full"
        )
    )
    messages = response.get("messages")
    if not isinstance(messages, list):
        return []
    return [message for message in messages[:100] if isinstance(message, dict)]


def _save_gmail_message(
    session: Session, user: User, message: dict[str, object]
) -> Email | None:
    parsed = parse_gmail_message(message)
    external_id = parsed["external_message_id"]
    if not isinstance(external_id, str) or not external_id:
        return None
    email_record = session.scalar(
        select(Email).where(
            Email.user_id == user.id,
            Email.source == "gmail",
            Email.external_message_id == external_id,
        )
    )
    if email_record is None:
        email_record = Email(
            user_id=user.id,
            source="gmail",
            external_message_id=external_id,
        )
        session.add(email_record)
    for key, value in parsed.items():
        setattr(email_record, key, value)
    return email_record


def record_sent_gmail_message(
    session: Session,
    user: User,
    account: ConnectedAccount,
    draft: Draft,
    gmail_message_id: str,
    thread_id: str | None,
) -> Email:
    email_record = session.scalar(
        select(Email).where(
            Email.user_id == user.id,
            Email.source == "gmail",
            Email.external_message_id == gmail_message_id,
        )
    )
    if email_record is None:
        email_record = Email(
            user_id=user.id,
            source="gmail",
            external_message_id=gmail_message_id,
        )
        session.add(email_record)
    email_record.thread_id = thread_id
    email_record.sender = account.email_address or "me"
    email_record.recipients = [*draft.recipients, *draft.cc]
    email_record.subject = draft.subject
    email_record.body = draft.body
    email_record.html_body = None
    email_record.preview = " ".join(draft.body.split())[:500] or None
    email_record.is_read = True
    email_record.is_sent = True
    email_record.is_starred = False
    email_record.is_priority = False
    email_record.received_at = datetime.now(timezone.utc)
    return email_record


def _message_ids(response: dict[str, object]) -> list[str]:
    messages = response.get("messages")
    if not isinstance(messages, list):
        return []
    return [
        message["id"]
        for message in messages
        if isinstance(message, dict)
        and isinstance(message.get("id"), str)
        and message["id"]
    ]


def _history_message_ids(response: dict[str, object]) -> list[str]:
    results: list[str] = []
    history_records = response.get("history")
    if not isinstance(history_records, list):
        return results
    for record in history_records:
        if not isinstance(record, dict):
            continue
        for field in ("messagesAdded", "labelsAdded", "labelsRemoved"):
            changes = record.get(field)
            if not isinstance(changes, list):
                continue
            for change in changes:
                message = change.get("message") if isinstance(change, dict) else None
                message_id = message.get("id") if isinstance(message, dict) else None
                if isinstance(message_id, str) and message_id not in results:
                    results.append(message_id)
    return results


def _collect_incremental_ids(
    service: Resource,
    account: ConnectedAccount,
    maximum: int,
) -> tuple[list[str], str | None, list[str], bool]:
    ids: list[str] = []
    seen: set[str] = set()
    pending = list(account.gmail_pending_message_ids or [])
    page_token = account.gmail_history_page_token
    continuing = account.gmail_pending_history_id is not None

    while len(ids) < maximum:
        while pending and len(ids) < maximum:
            message_id = pending.pop(0)
            if message_id not in seen:
                ids.append(message_id)
                seen.add(message_id)
        if len(ids) >= maximum:
            return ids, page_token, pending, not page_token and not pending
        if continuing and not page_token and not pending:
            return ids, None, [], True

        response = _execute(
            service.users()
            .history()
            .list(
                userId="me",
                startHistoryId=account.gmail_history_id,
                maxResults=100,
                pageToken=page_token,
            )
        )
        continuing = True
        page_token_value = response.get("nextPageToken")
        page_token = (
            page_token_value
            if isinstance(page_token_value, str) and page_token_value
            else None
        )
        pending.extend(
            message_id
            for message_id in _history_message_ids(response)
            if message_id not in seen and message_id not in pending
        )
        while pending and len(ids) < maximum:
            message_id = pending.pop(0)
            if message_id not in seen:
                ids.append(message_id)
                seen.add(message_id)
        if len(ids) >= maximum and (page_token or pending):
            return ids, page_token, pending, False
        if not page_token and not pending:
            return ids, None, [], True
    return ids, page_token, pending, not page_token and not pending


def _list_full_sync_ids(service: Resource, limit: int) -> list[str]:
    result: list[str] = []
    page_token: str | None = None
    while len(result) < limit:
        response = _execute(
            service.users()
            .messages()
            .list(
                userId="me",
                maxResults=min(100, limit - len(result)),
                pageToken=page_token,
            )
        )
        result.extend(_message_ids(response))
        token = response.get("nextPageToken")
        page_token = token if isinstance(token, str) and token else None
        if not page_token:
            break
    return result[:limit]


def sync_gmail(
    session: Session,
    user: User,
    account: ConnectedAccount,
    *,
    limit: int | None = None,
) -> dict[str, int | bool]:
    try:
        return _sync_gmail(session, user, account, limit=limit)
    except GmailReauthorizationRequired:
        session.rollback()
        _mark_reauthorization_required(session, account)
        raise
    except GmailError:
        session.rollback()
        raise


def _sync_gmail(
    session: Session,
    user: User,
    account: ConnectedAccount,
    *,
    limit: int | None,
) -> dict[str, int | bool]:
    configured_maximum = get_gmail_sync_limit()
    maximum = configured_maximum if limit is None else min(configured_maximum, limit)
    if not 1 <= maximum <= configured_maximum:
        raise ValueError("Gmail sync limit must be between 1 and 100")
    service = build_gmail_service(account, session)
    starting_profile = fetch_profile(service)
    starting_history_id = starting_profile.get("historyId")
    history_id = account.gmail_history_id
    is_incremental = bool(history_id)
    history_complete = True
    pending_history_id: str | None = None
    next_history_page_token: str | None = None
    pending_message_ids: list[str] = []

    if history_id:
        try:
            ids, next_history_page_token, pending_message_ids, history_complete = (
                _collect_incremental_ids(service, account, maximum)
            )
            pending_history_id = (
                None if history_complete else starting_history_id
            )
        except GmailHistoryExpired:
            # Gmail expires history IDs; a bounded full sync safely recovers without
            # deleting local data based on incomplete results.
            ids = _list_full_sync_ids(service, maximum)
            is_incremental = False
            history_complete = True
            account.gmail_history_page_token = None
            account.gmail_pending_message_ids = []
            account.gmail_pending_history_id = None
    else:
        ids = _list_full_sync_ids(service, maximum)

    synced = 0
    for message_id in ids:
        message = fetch_message(service, message_id)
        if _save_gmail_message(session, user, message) is not None:
            synced += 1

    latest_profile = fetch_profile(service)
    selected_history_id = (
        account.gmail_pending_history_id
        if is_incremental and history_complete and account.gmail_pending_history_id
        else starting_history_id
        if not is_incremental or history_complete
        else account.gmail_history_id
    )
    if isinstance(selected_history_id, (str, int)):
        account.gmail_history_id = str(selected_history_id)
    account.gmail_history_page_token = (
        next_history_page_token if is_incremental and not history_complete else None
    )
    account.gmail_pending_message_ids = pending_message_ids
    account.gmail_pending_history_id = pending_history_id
    account.last_synced_at = datetime.now(timezone.utc)
    email_address = latest_profile.get("emailAddress")
    if isinstance(email_address, str):
        account.email_address = email_address[:320]
    session.commit()
    return {"synced": synced, "incremental": is_incremental}


def sync_thread(
    session: Session, user: User, account: ConnectedAccount, thread_id: str
) -> list[Email]:
    try:
        service = build_gmail_service(account, session)
        messages = fetch_thread(service, thread_id)
        records: list[Email] = []
        for message in messages:
            record = _save_gmail_message(session, user, message)
            if record is not None:
                records.append(record)
        session.commit()
        return records
    except GmailReauthorizationRequired:
        session.rollback()
        _mark_reauthorization_required(session, account)
        raise
    except GmailError:
        session.rollback()
        raise


def gmail_status(session: Session, user: User) -> dict[str, object]:
    account = get_gmail_account(session, user)
    if account is None:
        return {
            "connected": False,
            "email": None,
            "status": "not_connected",
            "last_synced_at": None,
            "requires_reconnect": False,
            "compose_enabled": False,
        }
    return {
        "connected": account.status == "connected",
        "email": account.email_address,
        "status": account.status,
        "last_synced_at": account.last_synced_at,
        "requires_reconnect": account.status != "connected",
        "compose_enabled": (
            account.status == "connected"
            and GMAIL_COMPOSE_SCOPE in (account.granted_scopes or [])
        ),
    }


def disconnect_gmail(session: Session, user: User) -> bool:
    account = session.scalar(
        select(ConnectedAccount)
        .where(
            ConnectedAccount.user_id == user.id,
            ConnectedAccount.provider == GMAIL_PROVIDER,
        )
        .with_for_update()
    )
    if account is None:
        return False
    account.status = "disconnected"
    account.access_token_encrypted = None
    account.refresh_token_encrypted = None
    account.token_expires_at = None
    account.gmail_history_id = None
    account.gmail_history_page_token = None
    account.gmail_pending_message_ids = []
    account.gmail_pending_history_id = None
    session.commit()
    return True
