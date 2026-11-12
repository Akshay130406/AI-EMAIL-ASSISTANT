from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.models.base import Base


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_connected_account_identity"),
        UniqueConstraint("user_id", "provider", name="uq_connected_account_user_provider"),
        CheckConstraint(
            "status IN ('connected', 'disconnected', 'pending')",
            name="ck_connected_account_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    provider_account_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    email_address: Mapped[str | None] = mapped_column(String(320))
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    gmail_history_id: Mapped[str | None] = mapped_column(String(255))
    gmail_history_page_token: Mapped[str | None] = mapped_column(Text)
    gmail_pending_message_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    gmail_pending_history_id: Mapped[str | None] = mapped_column(String(255))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="connected_accounts")


from app.models.user import User
