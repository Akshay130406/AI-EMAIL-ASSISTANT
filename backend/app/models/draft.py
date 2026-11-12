from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.models.base import Base


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'ready', 'archived')", name="ck_draft_status"
        ),
        CheckConstraint(
            "send_status IN ('not_sent', 'sending', 'sent', 'unknown', 'failed')",
            name="ck_draft_send_status",
        ),
        UniqueConstraint("gmail_draft_id", name="uq_draft_gmail_draft_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipient: Mapped[str | None] = mapped_column(String(320))
    recipients: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    cc: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    bcc: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    subject: Mapped[str] = mapped_column(String(998), default="", server_default="")
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")
    gmail_draft_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gmail_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    send_status: Mapped[str] = mapped_column(
        String(20), default="not_sent", server_default="not_sent"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="drafts")


from app.models.user import User
