from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.models.base import Base


class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_message_id", name="uq_email_external_source"),
        CheckConstraint("source IN ('sample', 'gmail')", name="ck_email_source"),
        Index("ix_emails_user_received", "user_id", "received_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    external_message_id: Mapped[str | None] = mapped_column(String(255))
    thread_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(20), default="sample", server_default="sample")
    sender: Mapped[str] = mapped_column(String(320))
    recipients: Mapped[list[str]] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(998), default="", server_default="")
    body: Mapped[str | None] = mapped_column(Text)
    html_body: Mapped[str | None] = mapped_column(Text)
    preview: Mapped[str | None] = mapped_column(String(500))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_priority: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="emails")


from app.models.user import User
