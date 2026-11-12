from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, StringConstraints, field_validator, model_validator
from typing_extensions import Annotated

from app.schemas.common import APIModel

CalendarMailbox = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=6,
        max_length=320,
        pattern=r"^[^@\s,<>]+@[^@\s,<>]+\.[^@\s,<>]+$",
    ),
]


class CalendarStatusRead(APIModel):
    connected: bool
    status: Literal["connected", "disconnected", "not_connected"]
    email: str | None = None
    requires_reconnect: bool = False


class CalendarConnectRead(APIModel):
    authorization_url: str


class CalendarRead(APIModel):
    id: str
    summary: str
    time_zone: str | None = None
    primary: bool = False
    access_role: str | None = None


class CalendarListRead(APIModel):
    items: list[CalendarRead]
    next_page_token: str | None = None


class CalendarEventRead(APIModel):
    id: str
    calendar_id: str
    summary: str
    description: str = ""
    start: str
    end: str
    time_zone: str | None = None
    attendees: list[str] = Field(default_factory=list)
    html_link: str | None = None
    status: str | None = None


class CalendarEventPage(APIModel):
    items: list[CalendarEventRead]
    next_page_token: str | None = None


class CalendarEventWrite(APIModel):
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=250)]
    description: Annotated[str, StringConstraints(max_length=10000)] = ""
    start: datetime
    end: datetime
    time_zone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    attendees: list[CalendarMailbox] = Field(default_factory=list, max_length=100)

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("A valid IANA time zone is required") from error
        return value

    @model_validator(mode="after")
    def validate_event_times(self) -> "CalendarEventWrite":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Start and end must include timezone offsets")
        if self.end <= self.start:
            raise ValueError("Event end must be after its start")
        return self


class CalendarEventCreate(CalendarEventWrite):
    request_id: UUID
    confirm: Literal[True]


class CalendarEventUpdate(CalendarEventWrite):
    confirm: Literal[True]


class CalendarConflictRequest(APIModel):
    start: datetime
    end: datetime
    time_zone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    exclude_event_id: str | None = Field(default=None, max_length=255)

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("A valid IANA time zone is required") from error
        return value

    @model_validator(mode="after")
    def validate_times(self) -> "CalendarConflictRequest":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Start and end must include timezone offsets")
        if self.end <= self.start:
            raise ValueError("End must be after start")
        return self


class CalendarConflictRead(APIModel):
    conflicts: list[CalendarEventRead]
    calendar_id: str


class CalendarDeleteRequest(APIModel):
    confirm: Literal[True]


class CalendarAvailabilityRequest(APIModel):
    date: date
    time_zone: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    duration_minutes: int = Field(ge=15, le=480)
    workday_start_hour: int = Field(default=9, ge=0, le=23)
    workday_end_hour: int = Field(default=17, ge=1, le=24)

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("A valid IANA time zone is required") from error
        return value

    @model_validator(mode="after")
    def validate_workday(self) -> "CalendarAvailabilityRequest":
        if self.workday_end_hour <= self.workday_start_hour:
            raise ValueError("Workday end must be later than its start")
        return self


class CalendarSlotRead(APIModel):
    start: datetime
    end: datetime
    time_zone: str
    calendar_free: bool


class CalendarAvailabilityRead(APIModel):
    time_zone: str
    slots: list[CalendarSlotRead]
    availability_scope: Literal["connected_user_calendar_only"] = "connected_user_calendar_only"


class MeetingAssistantRequest(APIModel):
    operation: Literal["agenda", "summary", "extract"]
    email_ids: list[UUID] = Field(default_factory=list, max_length=5)
    event_id: str | None = Field(default=None, max_length=255)
    calendar_id: str = Field(default="primary", min_length=1, max_length=255)
    question: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def require_context(self) -> "MeetingAssistantRequest":
        if not self.event_id and not self.email_ids:
            raise ValueError("Select a calendar event or at least one Gmail message")
        return self


class MeetingAssistantRead(APIModel):
    title: str = Field(default="", max_length=250)
    summary: str = Field(default="", max_length=2000)
    agenda: list[str] = Field(default_factory=list, max_length=10)
    attendees: list[str] = Field(default_factory=list, max_length=20)
    suggested_times: list[str] = Field(default_factory=list, max_length=5)
    source_email_ids: list[UUID] = Field(default_factory=list, max_length=5)
    calendar_availability_confirmed: bool = False
