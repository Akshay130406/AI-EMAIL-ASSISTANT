from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import StringConstraints
from typing_extensions import Annotated

from app.schemas.common import APIModel, PageResponse

MessageRole = Literal["user", "assistant"]


class ConversationCreate(APIModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = "New conversation"


class ConversationRead(APIModel):
    id: UUID
    user_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(PageResponse[ConversationRead]):
    pass


class ConversationMessageCreate(APIModel):
    role: MessageRole
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100_000)]


class ConversationMessageRead(APIModel):
    id: UUID
    conversation_id: UUID
    role: MessageRole | Literal["system"]
    content: str
    created_at: datetime


class ConversationMessageListResponse(PageResponse[ConversationMessageRead]):
    pass
