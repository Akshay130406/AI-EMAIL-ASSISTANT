from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import APIModel

AutomationKind = Literal["gmail_sync", "daily_briefing", "follow_up_reminder"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class AutomationCreate(APIModel):
    kind: AutomationKind
    interval_minutes: int = Field(default=1440, ge=15, le=10080)
    enabled: bool = False


class AutomationUpdate(APIModel):
    interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "AutomationUpdate":
        if self.interval_minutes is None and self.enabled is None:
            raise ValueError("Provide at least one automation setting")
        return self


class AutomationRead(APIModel):
    id: UUID
    kind: AutomationKind
    enabled: bool
    interval_minutes: int
    next_run_at: datetime
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BackgroundJobRead(APIModel):
    id: UUID
    automation_id: UUID | None
    job_type: AutomationKind
    status: JobStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_error_code: str | None
    result_summary: str | None
    created_at: datetime
    updated_at: datetime


class JobPage(APIModel):
    items: list[BackgroundJobRead]
    total: int
    page: int
    page_size: int


class NotificationRead(APIModel):
    id: UUID
    source_job_id: UUID | None
    kind: Literal[
        "gmail_sync", "daily_briefing", "follow_up_reminder", "job"
    ]
    title: str
    message: str
    data: dict[str, object]
    read_at: datetime | None
    created_at: datetime


class NotificationPage(APIModel):
    items: list[NotificationRead]
    total: int
    unread_count: int
    page: int
    page_size: int


class NotificationReadUpdate(APIModel):
    read: bool
