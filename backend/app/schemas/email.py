from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import APIModel, PageResponse, TimestampedResponse


class EmailRead(TimestampedResponse):
    user_id: UUID
    external_message_id: str | None
    thread_id: str | None
    source: str
    sender: str
    recipients: list[str]
    subject: str
    body: str | None
    html_body: str | None
    preview: str | None
    is_read: bool
    is_sent: bool = False
    is_starred: bool
    is_priority: bool
    received_at: datetime | None


class EmailListResponse(PageResponse[EmailRead]):
    pass


class EmailPatch(APIModel):
    is_read: bool | None = None
    is_starred: bool | None = None
    is_priority: bool | None = None

    def changes(self) -> dict[str, bool]:
        return {
            key: value
            for key, value in self.model_dump(exclude_unset=True).items()
            if value is not None
        }
