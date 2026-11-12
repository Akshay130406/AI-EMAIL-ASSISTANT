from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import CurrentUser, CsrfProtectedUser, DatabaseSession
from app.schemas.conversation import (
    ConversationCreate,
    ConversationListResponse,
    ConversationMessageCreate,
    ConversationMessageListResponse,
    ConversationMessageRead,
    ConversationRead,
)
from app.services.conversations import (
    create_conversation,
    create_message,
    get_conversation,
    list_conversations,
    list_messages,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationListResponse)
def conversations_list(
    session: DatabaseSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ConversationListResponse:
    return ConversationListResponse(
        **list_conversations(session, user, page=page, page_size=page_size)
    )


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def conversation_create(
    payload: ConversationCreate, session: DatabaseSession, user: CsrfProtectedUser
) -> ConversationRead:
    return ConversationRead.model_validate(
        create_conversation(session, user, payload.title)
    )


@router.get(
    "/{conversation_id}/messages",
    response_model=ConversationMessageListResponse,
)
def conversation_messages(
    conversation_id: UUID,
    session: DatabaseSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ConversationMessageListResponse:
    conversation = get_conversation(session, user, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return ConversationMessageListResponse(
        **list_messages(session, conversation, page=page, page_size=page_size)
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationMessageRead,
    status_code=status.HTTP_201_CREATED,
)
def conversation_message_create(
    conversation_id: UUID,
    payload: ConversationMessageCreate,
    session: DatabaseSession,
    user: CsrfProtectedUser,
) -> ConversationMessageRead:
    conversation = get_conversation(session, user, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    message = create_message(session, conversation, payload.role, payload.content)
    return ConversationMessageRead.model_validate(message)
