from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AutomationRule, BackgroundJob, Notification, User

MAX_PENDING_JOBS_PER_USER = 5
MAX_MANUAL_RUNS_PER_HOUR = 10
MAX_SCHEDULER_BATCH = 100


class AutomationNotFound(LookupError):
    pass


class JobNotFound(LookupError):
    pass


class JobNotCancellable(ValueError):
    pass


class AutomationAlreadyExists(ValueError):
    pass


class AutomationQueueLimit(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def list_automations(session: Session, user: User) -> list[AutomationRule]:
    return list(
        session.scalars(
            select(AutomationRule)
            .where(AutomationRule.user_id == user.id)
            .order_by(AutomationRule.created_at)
        )
    )


def create_automation(
    session: Session,
    user: User,
    *,
    kind: str,
    interval_minutes: int,
    enabled: bool,
) -> AutomationRule:
    existing = session.scalar(
        select(AutomationRule).where(
            AutomationRule.user_id == user.id,
            AutomationRule.kind == kind,
        )
    )
    if existing is not None:
        raise AutomationAlreadyExists
    now = utc_now()
    rule = AutomationRule(
        user_id=user.id,
        kind=kind,
        interval_minutes=interval_minutes,
        enabled=enabled,
        next_run_at=now + timedelta(minutes=interval_minutes),
    )
    session.add(rule)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        existing = session.scalar(
            select(AutomationRule.id).where(
                AutomationRule.user_id == user.id,
                AutomationRule.kind == kind,
            )
        )
        if existing is not None:
            raise AutomationAlreadyExists from error
        raise
    session.refresh(rule)
    return rule


def get_automation(
    session: Session, user: User, automation_id: UUID
) -> AutomationRule:
    rule = session.scalar(
        select(AutomationRule).where(
            AutomationRule.id == automation_id,
            AutomationRule.user_id == user.id,
        )
    )
    if rule is None:
        raise AutomationNotFound
    return rule


def update_automation(
    session: Session,
    user: User,
    automation_id: UUID,
    *,
    interval_minutes: int | None,
    enabled: bool | None,
) -> AutomationRule:
    rule = get_automation(session, user, automation_id)
    now = utc_now()
    changed_schedule = False
    if interval_minutes is not None and interval_minutes != rule.interval_minutes:
        rule.interval_minutes = interval_minutes
        changed_schedule = True
    if enabled is not None and enabled != rule.enabled:
        rule.enabled = enabled
        changed_schedule = True
    if rule.enabled and changed_schedule:
        rule.next_run_at = now + timedelta(minutes=rule.interval_minutes)
    session.commit()
    session.refresh(rule)
    return rule


def delete_automation(
    session: Session, user: User, automation_id: UUID
) -> None:
    rule = get_automation(session, user, automation_id)
    session.execute(
        update(BackgroundJob)
        .where(BackgroundJob.automation_id == rule.id)
        .values(automation_id=None)
    )
    session.delete(rule)
    session.commit()


def _pending_job_count(session: Session, user_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(
                BackgroundJob.user_id == user_id,
                BackgroundJob.status.in_(("queued", "running")),
            )
        )
        or 0
    )


def queue_job(
    session: Session,
    *,
    user_id: UUID,
    job_type: str,
    idempotency_key: str,
    automation_id: UUID | None = None,
    available_at: datetime | None = None,
) -> BackgroundJob:
    locked_user = session.scalar(
        select(User.id).where(User.id == user_id).with_for_update()
    )
    if locked_user is None:
        raise LookupError("Job owner not found")
    existing = session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.user_id == user_id,
            BackgroundJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    if _pending_job_count(session, user_id) >= MAX_PENDING_JOBS_PER_USER:
        raise AutomationQueueLimit
    job = BackgroundJob(
        user_id=user_id,
        automation_id=automation_id,
        job_type=job_type,
        idempotency_key=idempotency_key,
        available_at=available_at or utc_now(),
        payload={},
    )
    session.add(job)
    session.flush()
    return job


def request_manual_run(
    session: Session,
    user: User,
    automation_id: UUID,
) -> BackgroundJob:
    locked_user = session.scalar(select(User.id).where(User.id == user.id).with_for_update())
    if locked_user is None:
        raise LookupError("Job owner not found")
    rule = get_automation(session, user, automation_id)
    recent_count = int(
        session.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(
                BackgroundJob.user_id == user.id,
                BackgroundJob.idempotency_key.like("manual:%"),
                BackgroundJob.created_at >= utc_now() - timedelta(hours=1),
            )
        )
        or 0
    )
    if recent_count >= MAX_MANUAL_RUNS_PER_HOUR:
        raise AutomationQueueLimit
    job = queue_job(
        session,
        user_id=user.id,
        job_type=rule.kind,
        automation_id=rule.id,
        idempotency_key=f"manual:{uuid4()}",
    )
    session.commit()
    session.refresh(job)
    return job


def enqueue_due_automations(session: Session, *, now: datetime | None = None) -> int:
    current_time = now or utc_now()
    rules = list(
        session.scalars(
            select(AutomationRule)
            .where(
                AutomationRule.enabled.is_(True),
                AutomationRule.next_run_at <= current_time,
            )
            .order_by(AutomationRule.next_run_at)
            .limit(MAX_SCHEDULER_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    enqueued = 0
    for rule in rules:
        scheduled_time = _aware(rule.next_run_at)
        interval = timedelta(minutes=rule.interval_minutes)
        elapsed = max(0.0, (current_time - scheduled_time).total_seconds())
        missed_intervals = int(elapsed // interval.total_seconds()) + 1
        rule.next_run_at = scheduled_time + interval * missed_intervals
        key = f"scheduled:{rule.id}:{scheduled_time.isoformat()}"
        existing = session.scalar(
            select(BackgroundJob.id).where(
                BackgroundJob.user_id == rule.user_id,
                BackgroundJob.idempotency_key == key,
            )
        )
        if existing is None:
            if _pending_job_count(session, rule.user_id) >= MAX_PENDING_JOBS_PER_USER:
                continue
            job = queue_job(
                session,
                user_id=rule.user_id,
                job_type=rule.kind,
                automation_id=rule.id,
                idempotency_key=key,
                available_at=current_time,
            )
            enqueued += 1
    session.commit()
    return enqueued


def list_jobs(
    session: Session,
    user: User,
    *,
    page: int,
    page_size: int,
) -> tuple[list[BackgroundJob], int]:
    statement = select(BackgroundJob).where(BackgroundJob.user_id == user.id)
    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    items = list(
        session.scalars(
            statement.order_by(BackgroundJob.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return items, total


def cancel_job(session: Session, user: User, job_id: UUID) -> BackgroundJob:
    job = session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.id == job_id,
            BackgroundJob.user_id == user.id,
        )
    )
    if job is None:
        raise JobNotFound
    if job.status != "queued":
        raise JobNotCancellable
    job.status = "cancelled"
    job.finished_at = utc_now()
    job.updated_at = utc_now()
    session.commit()
    session.refresh(job)
    return job


def list_notifications(
    session: Session,
    user: User,
    *,
    page: int,
    page_size: int,
) -> tuple[list[Notification], int, int]:
    base = select(Notification).where(Notification.user_id == user.id)
    total = int(session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    unread_count = int(
        session.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.user_id == user.id,
                Notification.read_at.is_(None),
            )
        )
        or 0
    )
    items = list(
        session.scalars(
            base.order_by(Notification.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return items, total, unread_count


def update_notification_read(
    session: Session,
    user: User,
    notification_id: UUID,
    *,
    read: bool,
) -> Notification:
    notification = session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    if notification is None:
        raise LookupError("Notification not found")
    notification.read_at = utc_now() if read else None
    session.commit()
    session.refresh(notification)
    return notification
