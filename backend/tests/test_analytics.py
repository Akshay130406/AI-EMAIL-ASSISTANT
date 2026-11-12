from datetime import datetime, timezone
from uuid import uuid4

from app.models import ConnectedAccount, Email, User
from tests.helpers import get_development_user


def _insert_email(session, user_id, source, *, day, sent=False, read=False):
    email = Email(
        user_id=user_id,
        source=source,
        external_message_id=f"{source}-{uuid4()}",
        sender="sender@example.test",
        recipients=[],
        subject=f"{source} message",
        body="A test message",
        is_sent=sent,
        is_read=read,
        is_starred=True,
        is_priority=not read,
        received_at=datetime.combine(day, datetime.min.time(), timezone.utc),
    )
    session.add(email)


def test_analytics_uses_sample_data_without_gmail_and_fills_empty_days(
    client, db_session_factory
):
    from app.services.analytics import get_analytics_overview
    from datetime import date

    user = get_development_user(db_session_factory)
    today = date(2030, 1, 7)
    with db_session_factory() as session:
        _insert_email(session, user.id, "sample", day=date(2030, 1, 7))
        _insert_email(session, user.id, "sample", day=date(2030, 1, 6), sent=True)
        _insert_email(session, user.id, "gmail", day=date(2030, 1, 7))
        session.commit()
        result = get_analytics_overview(session, session.get(User, user.id), period_days=7, today=today)

    assert result["source"] == "sample"
    assert result["total_received"] == 1
    assert result["total_sent"] == 1
    assert result["unread"] == 1
    assert len(result["daily"]) == 7
    assert result["daily"][0]["received"] == 0
    assert result["daily"][-1]["received"] == 1


def test_analytics_uses_only_connected_users_gmail_data(
    client, db_session_factory
):
    from datetime import date

    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        foreign = User(email="foreign-analytics@example.test")
        session.add(foreign)
        session.flush()
        session.add(
            ConnectedAccount(
                user_id=user.id,
                provider="gmail",
                provider_account_id="analytics-gmail",
                status="connected",
            )
        )
        _insert_email(session, user.id, "sample", day=date.today())
        _insert_email(session, user.id, "gmail", day=date.today(), read=False)
        _insert_email(session, foreign.id, "gmail", day=date.today(), sent=True)
        session.commit()

    response = client.get("/api/analytics/overview?period_days=7")
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "gmail"
    assert data["total_received"] == 1
    assert data["total_sent"] == 0
    assert data["unread"] == 1
    assert data["priority"] == 1


def test_analytics_requires_authentication(unauthenticated_client):
    assert unauthenticated_client.get("/api/analytics/overview").status_code == 401
