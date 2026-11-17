from __future__ import annotations

import logging
import time
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session, aliased, sessionmaker

from app.models import AutomationRule, BackgroundJob, Email, Notification, User
from app.services import ai
from app.services import auto_reply
from app.services import automation as automation_service
from app.services import gmail

logger = logging.getLogger(__name__)
JOB_LEASE_SECONDS = 900
MAX_FOLLOW_UP_EMAILS = 10


def _failure(error: Exception) -> tuple[str, bool]:
    if isinstance(error, gmail.GmailNotConnected):
        return "GMAIL_NOT_CONNECTED", False
    if isinstance(error, gmail.GmailReauthorizationRequired):
        return "GMAIL_REAUTHORIZATION_REQUIRED", False
    if isinstance(error, gmail.GmailRateLimited):
        return "GMAIL_RATE_LIMITED", True
    if isinstance(error, gmail.GmailAPIUnavailable):
        return "GMAIL_TEMPORARILY_UNAVAILABLE", True
    if isinstance(error, ai.AIGmailNotConnected):
        return "GMAIL_NOT_CONNECTED", False
    if isinstance(error, ai.AIConfigurationMissing):
        return "GEMINI_NOT_CONFIGURED", False
    if isinstance(error, ai.AIUsageLimitExceeded):
        return "AI_USAGE_LIMIT_REACHED", True
    if isinstance(error, ai.AIProviderRateLimited):
        return "GEMINI_RATE_LIMITED", True
    if isinstance(error, ai.AIProviderTimeout):
        return "GEMINI_TIMEOUT", True
    if isinstance(error, ai.AIProviderUnavailable):
        return "GEMINI_TEMPORARILY_UNAVAILABLE", True
    if isinstance(error, ai.AIInputTooLarge):
        return "AI_CONTEXT_TOO_LARGE", False
    if isinstance(error, ai.AIInvalidOutput):
        return "GEMINI_INVALID_OUTPUT", False
    return "UNEXPECTED_ERROR", False


def _enqueue_stale_leases(session: Session, now) -> None:
    stale = (
        BackgroundJob.status == "running",
        BackgroundJob.lease_expires_at <= now,
    )
    session.execute(
        update(BackgroundJob)
        .where(*stale, BackgroundJob.attempts < BackgroundJob.max_attempts)
        .values(
            status="queued",
            available_at=now,
            lease_expires_at=None,
            lease_token=None,
            last_error_code="WORKER_LEASE_EXPIRED",
        )
    )
    session.execute(
        update(BackgroundJob)
        .where(*stale, BackgroundJob.attempts >= BackgroundJob.max_attempts)
        .values(
            status="failed",
            finished_at=now,
            lease_expires_at=None,
            lease_token=None,
            last_error_code="WORKER_LEASE_EXPIRED",
        )
    )


def claim_next_job(factory: sessionmaker[Session]) -> tuple[UUID, UUID] | None:
    now = automation_service.utc_now()
    with factory() as session:
        _enqueue_stale_leases(session, now)
        job = session.scalar(
            select(BackgroundJob)
            .where(
                BackgroundJob.status == "queued",
                BackgroundJob.available_at <= now,
            )
            .order_by(BackgroundJob.available_at, BackgroundJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            session.commit()
            return None
        token = uuid4()
        job.status = "running"
        job.attempts += 1
        job.started_at = job.started_at or now
        job.lease_expires_at = now + timedelta(seconds=JOB_LEASE_SECONDS)
        job.lease_token = token
        session.commit()
        return job.id, token


def _follow_up_data(session: Session, user_id: UUID) -> dict[str, object]:
    cutoff = automation_service.utc_now() - timedelta(days=2)
    newer_received = aliased(Email)
    later_sent = aliased(Email)
    candidates = list(
        session.execute(
            select(Email.id, Email.thread_id)
            .where(
                Email.user_id == user_id,
                Email.source == "gmail",
                Email.is_sent.is_(False),
                Email.thread_id.is_not(None),
                Email.received_at <= cutoff,
                ~exists(
                    select(1).where(
                        newer_received.user_id == Email.user_id,
                        newer_received.source == "gmail",
                        newer_received.is_sent.is_(False),
                        newer_received.thread_id == Email.thread_id,
                        newer_received.received_at > Email.received_at,
                    )
                ),
                ~exists(
                    select(1).where(
                        later_sent.user_id == Email.user_id,
                        later_sent.source == "gmail",
                        later_sent.is_sent.is_(True),
                        later_sent.thread_id == Email.thread_id,
                        later_sent.received_at >= Email.received_at,
                    )
                ),
            )
            .order_by(Email.received_at.desc())
            .limit(MAX_FOLLOW_UP_EMAILS)
        )
    )
    return {
        "email_ids": [str(email_id) for email_id, _thread_id in candidates],
        "review_count": len(candidates),
    }


def _run_job(session: Session, job: BackgroundJob, user: User) -> tuple[str, dict[str, object]]:
    if job.job_type == "gmail_sync":
        account = gmail.require_gmail_account(session, user)
        result = gmail.sync_gmail(session, user, account)
        synced = int(result["synced"])
        return (
            f"Gmail synchronization completed: {synced} message(s) processed.",
            {"synced": synced, "incremental": bool(result["incremental"])},
        )
    if job.job_type == "daily_briefing":
        result = ai.get_insights(session, user)
        data = {
            "computed": result.computed.model_dump(mode="json"),
            "ai_generated": result.ai_generated.model_dump(mode="json"),
            "sources": [source.model_dump(mode="json") for source in result.sources],
            "generated_at": result.generated_at,
        }
        return "Your daily inbox briefing is ready.", data
    if job.job_type == "follow_up_reminder":
        data = _follow_up_data(session, user.id)
        count = int(data["review_count"])
        return (
            f"{count} conversation(s) have no reply recorded in Mailmind; review them before following up.",
            data,
        )
    raise ValueError("Unsupported background job type")


def _complete_job(
    session: Session,
    job_id: UUID,
    lease_token: UUID,
    summary: str,
    data: dict[str, object],
) -> bool:
    job = session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == "running",
            BackgroundJob.lease_token == lease_token,
        )
    )
    if job is None:
        return False
    now = automation_service.utc_now()
    job.status = "succeeded"
    job.finished_at = now
    job.lease_expires_at = None
    job.lease_token = None
    job.result_summary = summary[:500]
    job.last_error_code = None
    if job.automation_id:
        rule = session.get(AutomationRule, job.automation_id)
        if rule is not None:
            rule.last_run_at = now
    session.add(
        Notification(
            user_id=job.user_id,
            source_job_id=job.id,
            kind=job.job_type,
            title={
                "gmail_sync": "Gmail synchronization complete",
                "daily_briefing": "Daily inbox briefing ready",
                "follow_up_reminder": "Follow-up review",
            }[job.job_type],
            message=summary,
            data=data,
            idempotency_key=f"job:{job.id}",
        )
    )
    session.commit()
    return True


def _fail_job(
    session: Session,
    job_id: UUID,
    lease_token: UUID,
    error: Exception,
) -> None:
    job = session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == "running",
            BackgroundJob.lease_token == lease_token,
        )
    )
    if job is None:
        return
    now = automation_service.utc_now()
    error_code, retryable = _failure(error)
    job.last_error_code = error_code
    job.lease_expires_at = None
    job.lease_token = None
    if retryable and job.attempts < job.max_attempts:
        job.status = "queued"
        job.available_at = now + timedelta(
            seconds=min(60 * (2 ** max(job.attempts - 1, 0)), 3600)
        )
    else:
        job.status = "failed"
        job.finished_at = now
    session.commit()
    logger.warning(
        "Background job %s failed (%s, retryable=%s)",
        job_id,
        error_code,
        retryable,
    )


def process_claimed_job(
    factory: sessionmaker[Session],
    job_id: UUID,
    lease_token: UUID,
) -> bool:
    with factory() as session:
        job = session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.id == job_id,
                BackgroundJob.status == "running",
                BackgroundJob.lease_token == lease_token,
            )
        )
        if job is None:
            return False
        user = session.get(User, job.user_id)
        if user is None:
            job.status = "failed"
            job.finished_at = automation_service.utc_now()
            job.last_error_code = "USER_NOT_FOUND"
            session.commit()
            return False
        try:
            summary, data = _run_job(session, job, user)
        except Exception as error:
            session.rollback()
            _fail_job(session, job_id, lease_token, error)
            return False
        return _complete_job(session, job_id, lease_token, summary, data)


def run_worker(
    factory: sessionmaker[Session],
    *,
    poll_interval_seconds: float = 3,
    once: bool = False,
) -> None:
    while True:
        with factory() as session:
            automation_service.enqueue_due_automations(session)
        auto_reply.run_due(factory)
        claim = claim_next_job(factory)
        if claim is None:
            if once:
                return
            time.sleep(poll_interval_seconds)
            continue
        process_claimed_job(factory, *claim)
        if once:
            return
