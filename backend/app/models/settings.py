from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.models.base import Base


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    theme: Mapped[str] = mapped_column(default="system", server_default="system")
    notification_preferences: Mapped[dict[str, bool]] = mapped_column(
        JSON,
        default=lambda: {
            "inbox_reminders": True,
            "writing_suggestions": True,
            "product_updates": False,
        },
    )
    ai_preferences: Mapped[dict[str, str | bool]] = mapped_column(
        JSON,
        default=lambda: {"default_tone": "professional", "always_review_drafts": True},
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="settings")


from app.models.user import User
