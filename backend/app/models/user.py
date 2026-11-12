from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    profile: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    connected_accounts: Mapped[list[ConnectedAccount]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    emails: Mapped[list[Email]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    drafts: Mapped[list[Draft]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    settings: Mapped[UserSettings | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    automations: Mapped[list[AutomationRule]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    background_jobs: Mapped[list[BackgroundJob]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


from app.models.connected_account import ConnectedAccount
from app.models.conversation import Conversation
from app.models.draft import Draft
from app.models.email import Email
from app.models.settings import UserSettings
from app.models.auth import UserSession
from app.models.automation import AutomationRule, BackgroundJob, Notification
