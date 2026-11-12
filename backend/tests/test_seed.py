from sqlalchemy import func, select

from app import seed
from app.models import Conversation, ConversationMessage, Email, User, UserSettings


def test_sample_seed_is_repeatable_and_development_only(
    db_session_factory, monkeypatch
):
    engine = db_session_factory.kw["bind"]
    monkeypatch.setattr(seed, "engine", engine)
    monkeypatch.setattr(seed, "SessionLocal", db_session_factory)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEV_USER_EMAIL", "developer@example.test")

    seed.seed_sample_data()
    seed.seed_sample_data()

    with db_session_factory() as session:
        user = session.scalar(select(User).where(User.email == "developer@example.test"))
        assert user is not None
        assert session.scalar(
            select(func.count()).select_from(Email).where(Email.user_id == user.id)
        ) == len(seed.SAMPLE_EMAILS)
        assert session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.user_id == user.id)
        ) == 1
        conversation = session.scalar(
            select(Conversation).where(Conversation.user_id == user.id)
        )
        assert len(conversation.messages) == 1
        assert session.scalar(
            select(func.count())
            .select_from(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation.id)
        ) == 1
        assert session.scalar(
            select(func.count())
            .select_from(UserSettings)
            .where(UserSettings.user_id == user.id)
        ) == 1

    monkeypatch.setenv("APP_ENV", "production")
    try:
        seed.seed_sample_data()
    except RuntimeError as error:
        assert "APP_ENV=development" in str(error)
    else:
        raise AssertionError("Production sample seeding must be rejected")
