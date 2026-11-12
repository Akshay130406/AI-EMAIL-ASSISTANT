from typing import Literal
from uuid import UUID

from pydantic import Field, StringConstraints, ValidationInfo, field_validator
from typing_extensions import Annotated

from app.schemas.common import APIModel, PageResponse, TimestampedResponse

DraftStatus = Literal["draft", "ready", "archived"]
Recipient = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]
Mailbox = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=6,
        max_length=320,
        pattern=r"^[^@\s,<>]+@[^@\s,<>]+\.[^@\s,<>]+$",
    ),
]


class GmailDraftRequest(APIModel):
    recipients: list[Mailbox] = Field(min_length=1, max_length=50)
    cc: list[Mailbox] = Field(default_factory=list, max_length=50)
    bcc: list[Mailbox] = Field(default_factory=list, max_length=50)
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=998)] = ""
    body: Annotated[str, StringConstraints(max_length=100_000)] = ""

    @field_validator("recipients", "cc", "bcc", mode="before")
    @classmethod
    def reject_duplicate_addresses(cls, values: object) -> object:
        if not isinstance(values, list):
            return values
        normalized = [value.strip().casefold() for value in values if isinstance(value, str)]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Recipient addresses must be unique within each field")
        return values

    @field_validator("recipients", "cc", "bcc")
    @classmethod
    def reject_cross_field_duplicates(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        seen = info.data.get("recipients", [])
        if info.field_name == "cc":
            seen = [*seen, *values]
        elif info.field_name == "bcc":
            seen = [*seen, *info.data.get("cc", []), *values]
        normalized = [value.casefold() for value in seen]
        if len(normalized) != len(set(normalized)):
            raise ValueError("An email address cannot appear in multiple recipient fields")
        return values

    @field_validator("subject")
    @classmethod
    def reject_subject_newlines(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("Subject cannot contain line breaks")
        return value


class DraftCreate(APIModel):
    recipient: Recipient | None = None
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=998)] = ""
    body: Annotated[str, StringConstraints(max_length=100_000)] = ""
    status: DraftStatus = "draft"


class DraftPatch(APIModel):
    recipient: Recipient | None = None
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=998)] | None = None
    body: Annotated[str, StringConstraints(max_length=100_000)] | None = None
    status: DraftStatus | None = None


class DraftRead(TimestampedResponse):
    user_id: UUID
    recipient: str | None
    recipients: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    status: DraftStatus
    gmail_draft_id: str | None = None
    gmail_message_id: str | None = None
    send_status: Literal["not_sent", "sending", "sent", "unknown", "failed"] = "not_sent"


class DraftListResponse(PageResponse[DraftRead]):
    pass
