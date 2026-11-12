from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.models.base import Base


AUTOMATION_KINDS = ("gmail_sync", "daily_briefing", "follow_up_reminder")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
JOB_TYPES = AUTOMATION_KINDS


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", name="uq_automation_user_kind"),
        CheckConstraint(
            "kind IN ('gmail_sync', 'daily_briefing', 'follow_up_reminder')",
            name="ck_automation_kind",
        ),
        CheckConstraint(
            "interval_minutes BETWEEN 15 AND 10080",
            name="ck_automation_interval",
        ),
        Index("ix_automation_due", "enabled", "next_run_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=1440, server_default="1440")
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="automations")
    jobs: Mapped[list["BackgroundJob"]] = relationship(back_populates="automation")


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('gmail_sync', 'daily_briefing', 'follow_up_reminder')",
            name="ck_background_job_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_background_job_status",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts BETWEEN 1 AND 5",
            name="ck_background_job_attempts",
        ),
        UniqueConstraint("user_id", "idempotency_key", name="uq_background_job_idempotency"),
        Index("ix_background_job_claim", "status", "available_at", "created_at"),
        Index("ix_background_job_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    automation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("automation_rules.id", ondelete="SET NULL")
    )
    job_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    idempotency_key: Mapped[str] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(60))
    result_summary: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="background_jobs")
    automation: Mapped[AutomationRule | None] = relationship(back_populates="jobs")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="source_job")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_notification_idempotency"),
        CheckConstraint(
            "kind IN ('gmail_sync', 'daily_briefing', 'follow_up_reminder', 'job')",
            name="ck_notification_kind",
        ),
        Index("ix_notification_user_created", "user_id", "created_at"),
        Index("ix_notification_user_read", "user_id", "read_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_job_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("background_jobs.id", ondelete="SET NULL"), unique=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="notifications")
    source_job: Mapped[BackgroundJob | None] = relationship(back_populates="notifications")


from app.models.user import User
