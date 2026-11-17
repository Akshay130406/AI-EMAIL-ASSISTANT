from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.models.base import Base


class AutoReplySettings(Base):
    __tablename__ = "auto_reply_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_auto_reply_settings_user"),
        CheckConstraint("daily_limit BETWEEN 1 AND 50", name="ck_auto_reply_daily_limit"),
        CheckConstraint("interval_minutes BETWEEN 15 AND 1440", name="ck_auto_reply_interval"),
        Index("ix_auto_reply_due", "enabled", "next_run_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    automatic_sending_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    daily_limit: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    reply_required_only: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    exclude_sensitive: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    allowed_senders: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    blocked_senders: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    include_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    exclude_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship()


class AutoReplyActivity(Base):
    __tablename__ = "auto_reply_activities"
    __table_args__ = (
        UniqueConstraint("user_id", "email_id", name="uq_auto_reply_activity_email"),
        CheckConstraint("status IN ('processing', 'draft_created', 'sent', 'skipped', 'failed', 'unknown')", name="ck_auto_reply_activity_status"),
        Index("ix_auto_reply_activity_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("emails.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="processing", server_default="processing")
    reason_code: Mapped[str | None] = mapped_column(String(60))
    gmail_draft_id: Mapped[str | None] = mapped_column(String(255))
    gmail_message_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship()
    email: Mapped["Email"] = relationship()


from app.models.email import Email
from app.models.user import User
