import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database.session import SessionLocal, engine
from app.models import Conversation, ConversationMessage, Email, User, UserSettings

logger = logging.getLogger(__name__)

SAMPLE_EMAILS = [
    {
        "external_message_id": "sample-message-001",
        "thread_id": "sample-thread-001",
        "sender": "Taylor Sample <taylor@example.test>",
        "recipients": ["sample-user@example.test"],
        "subject": "Sample project update",
        "preview": "An example message for local API development.",
        "body": "Hello,\n\nThis is fictional sample content for local development and testing only.\n\nThanks,\nTaylor",
        "is_read": False,
        "is_starred": True,
        "is_priority": True,
        "received_at": datetime.now(timezone.utc) - timedelta(hours=2),
    },
    {
        "external_message_id": "sample-message-002",
        "thread_id": "sample-thread-002",
        "sender": "Casey Example <casey@example.test>",
        "recipients": ["sample-user@example.test"],
        "subject": "Sample planning note",
        "preview": "A second fictional message for local API development.",
        "body": "Hi,\n\nAnother fictional example message. It does not contain real personal email content.\n\nBest,\nCasey",
        "is_read": True,
        "is_starred": False,
        "is_priority": False,
        "received_at": datetime.now(timezone.utc) - timedelta(days=1),
    },
]


def seed_sample_data() -> None:
    if os.getenv("APP_ENV", "production").strip().lower() != "development":
        raise RuntimeError("Sample seeding is permitted only when APP_ENV=development")
    if engine is None:
        raise RuntimeError("DATABASE_URL must be configured before sample seeding")
    sample_user_email = os.getenv("DEV_USER_EMAIL", "").strip().lower()
    if not sample_user_email:
        raise RuntimeError("DEV_USER_EMAIL must be configured before sample seeding")

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == sample_user_email))
        if user is None:
            user = User(email=sample_user_email, display_name="Development sample user")
            session.add(user)
            session.flush()

        for sample in SAMPLE_EMAILS:
            existing = session.scalar(
                select(Email).where(
                    Email.user_id == user.id,
                    Email.external_message_id == sample["external_message_id"],
                )
            )
            if existing is None:
                session.add(Email(user_id=user.id, **sample))

        if session.scalar(select(UserSettings).where(UserSettings.user_id == user.id)) is None:
            session.add(UserSettings(user_id=user.id))

        conversation = session.scalar(
            select(Conversation).where(
                Conversation.user_id == user.id,
                Conversation.title == "Sample development conversation",
            )
        )
        if conversation is None:
            conversation = Conversation(
                user_id=user.id, title="Sample development conversation"
            )
            session.add(conversation)
            session.flush()
            session.add(
                ConversationMessage(
                    conversation_id=conversation.id,
                    role="user",
                    content="This is a fictional sample conversation.",
                )
            )

        session.commit()
        logger.info("Sample development data is ready")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_sample_data()
