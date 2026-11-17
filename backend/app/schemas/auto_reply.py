from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.common import APIModel


class AutoReplySettingsRead(APIModel):
    enabled: bool
    automatic_sending_enabled: bool
    mode: Literal["off", "draft", "automatic_send"]
    interval_minutes: int
    daily_limit: int
    reply_required_only: bool
    exclude_sensitive: bool
    allowed_senders: list[str]
    blocked_senders: list[str]
    include_keywords: list[str]
    exclude_keywords: list[str]
    next_run_at: datetime | None
    gmail_connected: bool
    compose_enabled: bool

class AutoReplySettingsUpdate(APIModel):
    enabled: bool | None = None
    automatic_sending_enabled: bool | None = None
    confirm_automatic_sending: bool = False
    interval_minutes: int | None = Field(default=None, ge=15, le=1440)
    daily_limit: int | None = Field(default=None, ge=1, le=50)
    reply_required_only: bool | None = None
    exclude_sensitive: Literal[True] | None = None
    allowed_senders: list[str] | None = Field(default=None, max_length=100)
    blocked_senders: list[str] | None = Field(default=None, max_length=100)
    include_keywords: list[str] | None = Field(default=None, max_length=30)
    exclude_keywords: list[str] | None = Field(default=None, max_length=50)

    @field_validator("allowed_senders", "blocked_senders")
    @classmethod
    def normalize_senders(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        result = []
        for value in values:
            item = value.strip().casefold()
            if not item or len(item) > 320 or any(char.isspace() for char in item):
                raise ValueError("Sender rules must be email addresses or domains")
            if "@" not in item or (item.startswith("@") and "." not in item[1:]):
                raise ValueError("Sender rules must contain an email address or domain")
            result.append(item)
        return list(dict.fromkeys(result))

    @field_validator("include_keywords", "exclude_keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        result = [item.strip()[:80].casefold() for item in values if item.strip()]
        return list(dict.fromkeys(result))

    @model_validator(mode="after")
    def require_explicit_send_confirmation(self):
        if self.automatic_sending_enabled and not self.confirm_automatic_sending:
            raise ValueError("Confirm automatic sending explicitly before enabling it")
        return self


class AutoReplyActivityRead(APIModel):
    id: UUID
    email_id: UUID
    email_subject: str
    email_sender: str
    status: Literal["processing", "draft_created", "sent", "skipped", "failed", "unknown"]
    reason_code: str | None
    gmail_draft_id: str | None
    gmail_message_id: str | None
    created_at: datetime


class AutoReplyActivityPage(APIModel):
    items: list[AutoReplyActivityRead]
    total: int
    page: int
    page_size: int
