from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, ConversationMessage, User
from app.services.pagination import paginate


def list_conversations(session: Session, user: User, *, page: int, page_size: int):
    statement = (
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
    )
    return paginate(session, statement, page=page, page_size=page_size)


def get_conversation(session: Session, user: User, conversation_id):
    return session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user.id
        )
    )


def create_conversation(session: Session, user: User, title: str) -> Conversation:
    conversation = Conversation(user_id=user.id, title=title)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def list_messages(
    session: Session, conversation: Conversation, *, page: int, page_size: int
):
    statement = (
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
    )
    return paginate(session, statement, page=page, page_size=page_size)


def create_message(
    session: Session, conversation: Conversation, role: str, content: str
) -> ConversationMessage:
    message = ConversationMessage(
        conversation_id=conversation.id, role=role, content=content
    )
    conversation.updated_at = datetime.now(timezone.utc)
    session.add(message)
    session.commit()
    session.refresh(message)
    session.refresh(conversation)
    return message
