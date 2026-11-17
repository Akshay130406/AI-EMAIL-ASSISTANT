from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta, timezone
from email.utils import parseaddr
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import AutoReplyActivity, AutoReplySettings, ConnectedAccount, Draft, Email, User
from app.services import ai, gmail

logger = logging.getLogger(__name__)
SENSITIVE_PATTERN = re.compile(
    r"\b(password|passcode|one[- ]time code|\botp\b|verification code|"
    r"bank account|credit card|debit card|wire transfer|tax return|"
    r"social security|\bssn\b|passport|salary|payroll|invoice|payment details|"
    r"confidential|non[- ]disclosure|\bnda\b|personal information|"
    r"medical record|diagnosis|prescription|patient|attorney|lawyer|legal notice|"
    r"lawsuit|litigation|termination notice|disciplinary action|security breach|"
    r"account recovery|reset your credentials)\b",
    re.IGNORECASE,
)
NO_REPLY_PATTERN = re.compile(r"\b(no[- ]?reply|do not reply|donotreply|mailer-daemon)\b", re.I)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_settings(session: Session, user: User) -> AutoReplySettings:
    settings = session.scalar(select(AutoReplySettings).where(AutoReplySettings.user_id == user.id))
    if settings is None:
        settings = AutoReplySettings(user_id=user.id)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def account_capabilities(session: Session, user: User) -> tuple[bool, bool]:
    account = session.scalar(select(ConnectedAccount).where(
        ConnectedAccount.user_id == user.id,
        ConnectedAccount.provider == "gmail",
        ConnectedAccount.status == "connected",
    ))
    if account is None:
        return False, False
    return True, gmail.GMAIL_COMPOSE_SCOPE in (account.granted_scopes or [])


def update_settings(session: Session, user: User, values: dict[str, object]) -> AutoReplySettings:
    values = {key: value for key, value in values.items() if key != "confirm_automatic_sending"}
    settings = get_settings(session, user)
    if values.get("automatic_sending_enabled") is True:
        connected, compose_enabled = account_capabilities(session, user)
        if not connected or not compose_enabled:
            raise ValueError("Connect Gmail and enable Gmail draft/sending access before enabling automatic sending")
    was_enabled = settings.enabled
    will_enable = values.get("enabled") is True and not was_enabled
    for key, value in values.items():
        setattr(settings, key, value)
    if values.get("enabled") is False:
        settings.automatic_sending_enabled = False
    if will_enable:
        settings.enabled_at = utc_now()
    if settings.enabled and (not was_enabled or settings.next_run_at is None):
        settings.next_run_at = utc_now() + timedelta(minutes=settings.interval_minutes)
    if not settings.enabled:
        settings.next_run_at = None
    session.commit()
    session.refresh(settings)
    return settings


def emergency_off(session: Session, user: User) -> AutoReplySettings:
    settings = get_settings(session, user)
    settings.enabled = False
    settings.automatic_sending_enabled = False
    settings.next_run_at = None
    session.commit()
    session.refresh(settings)
    return settings


def list_activity(session: Session, user: User, *, page: int, page_size: int):
    base = select(AutoReplyActivity).where(AutoReplyActivity.user_id == user.id)
    total = int(session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    items = list(session.scalars(
        base.order_by(AutoReplyActivity.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ))
    return items, total


def _email_address(sender: str) -> str:
    address = parseaddr(sender)[1].strip().casefold()
    return address if "@" in address else ""


def _rule_reason(settings: AutoReplySettings, email: Email) -> str | None:
    address = _email_address(email.sender)
    if not address or NO_REPLY_PATTERN.search(email.sender):
        return "non_reply_address"
    domain = address.rsplit("@", 1)[1]
    blocked = {item.casefold() for item in settings.blocked_senders or []}
    if address in blocked or f"@{domain}" in blocked:
        return "sender_blocked"
    allowed = {item.casefold() for item in settings.allowed_senders or []}
    if allowed and address not in allowed and f"@{domain}" not in allowed:
        return "sender_not_allowed"
    content = f"{email.subject}\n{email.body or email.preview or ''}"
    folded = content.casefold()
    if any(item in folded for item in settings.exclude_keywords or []):
        return "excluded_keyword"
    includes = settings.include_keywords or []
    if includes and not any(item in folded for item in includes):
        return "no_included_keyword"
    if email.has_attachments:
        return "attachment_excluded"
    if SENSITIVE_PATTERN.search(content):
        return "sensitive_content"
    return None


def _claim_email(session: Session, user_id: UUID, email_id: UUID) -> AutoReplyActivity | None:
    activity = AutoReplyActivity(user_id=user_id, email_id=email_id, status="processing")
    session.add(activity)
    try:
        session.commit()
        session.refresh(activity)
        return activity
    except IntegrityError:
        session.rollback()
        return None


def _activity(session: Session, activity_id: UUID, status: str, reason: str | None = None) -> None:
    entry = session.get(AutoReplyActivity, activity_id)
    if entry is not None:
        entry.status = status
        entry.reason_code = reason
        session.commit()


def _daily_send_count(session: Session, user_id: UUID, now: datetime) -> int:
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    return int(session.scalar(select(func.count()).select_from(AutoReplyActivity).where(
        AutoReplyActivity.user_id == user_id,
        AutoReplyActivity.status.in_(("sent", "unknown")),
        AutoReplyActivity.updated_at >= start,
    )) or 0)


def process_user(session: Session, user: User, settings: AutoReplySettings) -> int:
    if not settings.enabled:
        return 0
    account = gmail.require_gmail_compose_account(session, user)
    gmail.sync_gmail(session, user, account)
    settings = session.scalar(select(AutoReplySettings).where(AutoReplySettings.id == settings.id))
    if settings is None or not settings.enabled:
        return 0
    candidates = list(session.scalars(
        select(Email).where(
            Email.user_id == user.id,
            Email.source == "gmail",
            Email.is_sent.is_(False),
            Email.received_at >= (settings.enabled_at or settings.created_at),
        ).order_by(Email.received_at.asc()).limit(25)
    ))
    processed = 0
    for email in candidates:
        if session.scalar(select(AutoReplyActivity.id).where(
            AutoReplyActivity.user_id == user.id,
            AutoReplyActivity.email_id == email.id,
        )):
            continue
        activity = _claim_email(session, user.id, email.id)
        if activity is None:
            continue
        processed += 1
        reason = _rule_reason(settings, email)
        if reason:
            _activity(session, activity.id, "skipped", reason)
            continue
        send_attempted = False
        try:
            if settings.reply_required_only:
                classification = ai.classify_email(session, user, email.id)
                if classification.response_required is not True:
                    _activity(session, activity.id, "skipped", "reply_not_required_or_uncertain")
                    continue
            suggestion = ai.suggest_reply(session, user, email.id)
            recipient = _email_address(email.sender)
            if not recipient or recipient == (account.email_address or "").casefold():
                _activity(session, activity.id, "skipped", "sender_not_replyable")
                continue
            raw = gmail.build_gmail_raw_message(
                recipients=[recipient], cc=[], bcc=[],
                subject=suggestion.subject or (email.subject if email.subject.lower().startswith("re:") else f"Re: {email.subject}"),
                body=suggestion.body,
            )
            active_settings = session.scalar(select(AutoReplySettings).where(
                AutoReplySettings.id == settings.id
            ).with_for_update())
            if active_settings is None or not active_settings.enabled:
                _activity(session, activity.id, "skipped", "disabled_during_processing")
                continue
            service = gmail.build_gmail_service(account, session)
            remote = gmail.create_remote_gmail_draft(service, raw)
            draft_id = remote.get("id")
            message = remote.get("message")
            if not isinstance(draft_id, str) or not isinstance(message, dict):
                raise gmail.GmailWriteOutcomeUnknown
            draft_info = gmail.parsed_gmail_draft(message)
            draft = Draft(
                user_id=user.id, recipient=recipient, recipients=[recipient], cc=[], bcc=[],
                subject=suggestion.subject or (email.subject if email.subject.lower().startswith("re:") else f"Re: {email.subject}"),
                body=suggestion.body, status="draft", gmail_draft_id=draft_id,
                gmail_message_id=draft_info.get("gmail_message_id"), send_status="not_sent",
            )
            session.add(draft)
            session.flush()
            activity.gmail_draft_id = draft_id
            session.commit()
            if not settings.automatic_sending_enabled:
                activity.status = "draft_created"
                activity.reason_code = None
                session.commit()
                continue

            # Recheck the emergency switch and daily cap immediately before sending.
            locked_settings = session.scalar(select(AutoReplySettings).where(
                AutoReplySettings.id == settings.id
            ).with_for_update())
            now = utc_now()
            if locked_settings is None or not locked_settings.enabled or not locked_settings.automatic_sending_enabled:
                activity.status = "draft_created"
                activity.reason_code = "sending_disabled_before_send"
                session.commit()
                continue
            if _daily_send_count(session, user.id, now) >= locked_settings.daily_limit:
                activity.status = "draft_created"
                activity.reason_code = "daily_limit_reached"
                session.commit()
                continue
            draft.send_status = "sending"
            session.commit()
            locked_settings = session.scalar(select(AutoReplySettings).where(
                AutoReplySettings.id == settings.id
            ).with_for_update())
            if locked_settings is None or not locked_settings.enabled or not locked_settings.automatic_sending_enabled:
                stored_draft = session.get(Draft, draft.id)
                stored_activity = session.get(AutoReplyActivity, activity.id)
                if stored_draft is not None:
                    stored_draft.send_status = "not_sent"
                if stored_activity is not None:
                    stored_activity.status = "draft_created"
                    stored_activity.reason_code = "sending_disabled_before_send"
                session.commit()
                continue
            # Keep the settings row locked through the send call so the emergency
            # switch cannot race between the final authorization check and Gmail.
            send_attempted = True
            sent = gmail.send_remote_gmail_draft(service, draft_id)
            message_id = sent.get("id")
            if not isinstance(message_id, str) or not message_id:
                raise gmail.GmailWriteOutcomeUnknown
            thread_id = sent.get("threadId")
            stored_draft = session.get(Draft, draft.id)
            stored_activity = session.get(AutoReplyActivity, activity.id)
            if stored_draft is None or stored_activity is None:
                raise gmail.GmailWriteOutcomeUnknown
            stored_draft.gmail_message_id = message_id
            stored_draft.send_status = "sent"
            stored_activity.gmail_message_id = message_id
            stored_activity.status = "sent"
            stored_activity.reason_code = None
            gmail.record_sent_gmail_message(
                session, user, account, stored_draft, message_id,
                thread_id if isinstance(thread_id, str) else None,
            )
            session.commit()
        except gmail.GmailWriteOutcomeUnknown:
            session.rollback()
            stored_draft = session.scalar(select(Draft).where(Draft.gmail_draft_id == activity.gmail_draft_id))
            if stored_draft is not None:
                stored_draft.send_status = "unknown"
                session.commit()
            _activity(session, activity.id, "unknown", "send_outcome_unknown")
        except gmail.GmailWriteRejected:
            session.rollback()
            stored_draft = session.scalar(select(Draft).where(Draft.gmail_draft_id == activity.gmail_draft_id))
            if stored_draft is not None:
                stored_draft.send_status = "failed"
                session.commit()
            _activity(session, activity.id, "failed", "gmail_rejected_send")
        except Exception as error:
            session.rollback()
            stored_draft = session.scalar(select(Draft).where(Draft.gmail_draft_id == activity.gmail_draft_id))
            status = "unknown" if send_attempted else "failed"
            if stored_draft is not None and stored_draft.send_status == "sending":
                stored_draft.send_status = status
                session.commit()
            _activity(session, activity.id, status, "send_outcome_unknown" if send_attempted else type(error).__name__[:60])
            logger.warning("Automatic reply processing failed (%s)", type(error).__name__)
    return processed


def run_due(factory: sessionmaker[Session], *, now: datetime | None = None) -> int:
    current = now or utc_now()
    with factory() as session:
        due = list(session.scalars(
            select(AutoReplySettings).where(
                AutoReplySettings.enabled.is_(True),
                AutoReplySettings.next_run_at.is_not(None),
                AutoReplySettings.next_run_at <= current,
            ).order_by(AutoReplySettings.next_run_at).limit(25).with_for_update(skip_locked=True)
        ))
        targets: list[tuple[UUID, UUID]] = []
        for settings in due:
            settings.next_run_at = current + timedelta(minutes=settings.interval_minutes)
            targets.append((settings.user_id, settings.id))
        session.commit()
    total = 0
    for user_id, settings_id in targets:
        with factory() as session:
            user = session.get(User, user_id)
            settings = session.get(AutoReplySettings, settings_id)
            if user is None or settings is None or not settings.enabled:
                continue
            try:
                total += process_user(session, user, settings)
            except Exception as error:
                logger.warning("Automatic reply cycle failed (%s)", type(error).__name__)
    return total
