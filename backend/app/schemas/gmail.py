from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.common import APIModel, PageResponse
from app.schemas.draft import DraftRead
from app.schemas.email import EmailRead


class GmailStatusRead(APIModel):
    connected: bool
    email: str | None
    status: str
    last_synced_at: datetime | None
    requires_reconnect: bool
    compose_enabled: bool = False


class GmailDraftsResponse(PageResponse[DraftRead]):
    pass


class GmailSendStatusRead(APIModel):
    draft_id: UUID
    status: Literal["not_sent", "sending", "sent", "unknown", "failed"]
    gmail_message_id: str | None = None


class GmailSendRequest(APIModel):
    confirm: Literal[True]


class GmailConnectRead(APIModel):
    authorization_url: str


class GmailSyncRead(APIModel):
    synced: int
    incremental: bool


class GmailThreadRead(APIModel):
    messages: list[EmailRead]
