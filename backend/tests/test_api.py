from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
import pytest

from app.models import ConnectedAccount, Conversation, Draft, Email, User, UserSettings
from app.services.auth import create_user_session
from app.services.settings import get_or_create_settings
from tests.helpers import get_development_user


def create_email(client, factory, *, subject: str, read: bool = False, starred: bool = False):
    client.get("/api/dashboard/overview")
    user = get_development_user(factory)
    with factory() as session:
        email = Email(
            user_id=user.id,
            external_message_id=f"external-{uuid4()}",
            thread_id="thread-sample",
            sender="Sample Sender <sender@example.test>",
            recipients=["developer@example.test"],
            subject=subject,
            preview="A safe fictional sample preview.",
            body="Fictional test email content.",
            is_read=read,
            is_starred=starred,
        )
        session.add(email)
        session.commit()
        session.refresh(email)
        return email.id


def test_dashboard_overview_aggregates_user_data(client, db_session_factory):
    create_email(client, db_session_factory, subject="Unread priority", starred=True)
    create_email(client, db_session_factory, subject="Already read", read=True)
    client.post("/api/drafts", json={"subject": "Draft"})
    client.post("/api/conversations", json={"title": "Sample conversation"})

    response = client.get("/api/dashboard/overview")

    assert response.status_code == 200
    assert response.json() == {
        "total_emails": 2,
        "unread_emails": 1,
        "starred_emails": 1,
        "priority_emails": 0,
        "drafts": 1,
        "conversations": 1,
    }


def test_email_listing_paginates_searches_and_filters(client, db_session_factory):
    create_email(client, db_session_factory, subject="Alpha status", starred=True)
    create_email(client, db_session_factory, subject="Beta project")
    create_email(client, db_session_factory, subject="Gamma notes", read=True)

    page = client.get("/api/emails?page=1&page_size=2")
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 2
    assert page.json()["page"] == 1

    search = client.get("/api/emails?search=Alpha")
    assert [item["subject"] for item in search.json()["items"]] == ["Alpha status"]

    unread = client.get("/api/emails?unread=true")
    assert {item["subject"] for item in unread.json()["items"]} == {
        "Alpha status",
        "Beta project",
    }
    starred = client.get("/api/emails?starred=true")
    assert [item["subject"] for item in starred.json()["items"]] == ["Alpha status"]


def test_email_detail_patch_and_validation(client, db_session_factory):
    email_id = create_email(client, db_session_factory, subject="Update me")

    assert client.get(f"/api/emails/{email_id}").status_code == 200
    updated = client.patch(
        f"/api/emails/{email_id}",
        json={"is_read": True, "is_starred": True, "is_priority": True},
    )
    assert updated.status_code == 200
    assert updated.json()["is_read"] is True
    assert updated.json()["is_starred"] is True
    assert updated.json()["is_priority"] is True
    assert client.patch(f"/api/emails/{email_id}", json={}).status_code == 422
    assert client.get("/api/emails?page=0").status_code == 422
    assert client.get("/api/emails?page_size=101").status_code == 422
    assert client.get(f"/api/emails/{uuid4()}").status_code == 404


def test_draft_crud_and_validation(client):
    created = client.post(
        "/api/drafts",
        json={
            "recipient": "reader@example.test",
            "subject": "A sample draft",
            "body": "Fictional draft body.",
        },
    )
    assert created.status_code == 201
    draft_id = created.json()["id"]
    assert client.get("/api/drafts").json()["total"] == 1
    assert client.get(f"/api/drafts/{draft_id}").status_code == 200

    updated = client.patch(f"/api/drafts/{draft_id}", json={"status": "ready"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "ready"
    assert client.patch(f"/api/drafts/{draft_id}", json={"status": "sent"}).status_code == 422
    assert client.patch(f"/api/drafts/{draft_id}", json={}).status_code == 422
    assert client.delete(f"/api/drafts/{draft_id}").status_code == 204
    assert client.get(f"/api/drafts/{draft_id}").status_code == 404
    assert client.delete(f"/api/drafts/{uuid4()}").status_code == 404


def test_conversation_messages_and_pagination(client):
    created = client.post("/api/conversations", json={"title": "Writing notes"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    assert client.get("/api/conversations").json()["total"] == 1

    first = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Help organize a sample email."},
    )
    second = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "assistant", "content": "This is a local sample response."},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert (
        client.get(f"/api/conversations/{conversation_id}/messages?page=1&page_size=1").json()[
            "total"
        ]
        == 2
    )
    assert client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "system", "content": "Role is not allowed from this endpoint."},
    ).status_code == 422
    assert client.get(f"/api/conversations/{uuid4()}/messages").status_code == 404


def test_settings_get_and_partial_update(client):
    current = client.get("/api/settings")
    assert current.status_code == 200
    assert current.json()["theme"] == "system"
    assert current.json()["ai_preferences"]["always_review_drafts"] is True

    updated = client.patch(
        "/api/settings",
        json={
            "theme": "dark",
            "notification_preferences": {"product_updates": True},
            "ai_preferences": {"default_tone": "friendly"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["theme"] == "dark"
    assert updated.json()["notification_preferences"] == {
        "inbox_reminders": True,
        "writing_suggestions": True,
        "product_updates": True,
    }
    assert updated.json()["ai_preferences"] == {
        "default_tone": "friendly",
        "always_review_drafts": True,
    }
    assert client.patch("/api/settings", json={"theme": "neon"}).status_code == 422
    assert client.patch("/api/settings", json={}).status_code == 422


def test_user_scoped_endpoints_do_not_leak_other_users(client, db_session_factory):
    email_id = create_email(client, db_session_factory, subject="Private to developer")
    original_session = client.session_token
    original_csrf = client.csrf_token
    with db_session_factory() as session:
        other_user = User(email="other@example.test", display_name="Other test user")
        session.add(other_user)
        session.commit()
        session.refresh(other_user)
        other_token, other_csrf, _ = create_user_session(session, other_user)
    client.set_session(other_token, other_csrf)
    assert client.get("/api/emails").json()["total"] == 0
    assert client.get("/api/drafts").json()["total"] == 0
    assert client.get("/api/conversations").json()["total"] == 0
    assert client.patch(
        f"/api/emails/{email_id}", json={"is_read": True}
    ).status_code == 404
    assert client.patch(
        "/api/settings", json={"theme": "dark"}
    ).status_code == 200

    client.set_session(original_session, original_csrf)
    developer_settings = client.get("/api/settings").json()
    assert developer_settings["theme"] == "system"


def test_model_relationships_constraints_and_no_plaintext_oauth_tokens(
    client, db_session_factory
):
    client.get("/api/dashboard/overview")
    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        settings = get_or_create_settings(session, session.get(User, user.id))
        account = ConnectedAccount(
            user_id=user.id,
            provider="google",
            provider_account_id="sample-google-account",
        )
        conversation = Conversation(user_id=user.id, title="Model relationship")
        session.add_all([account, conversation])
        session.commit()

        assert settings.user_id == user.id
        assert session.scalar(
            select(ConnectedAccount).where(ConnectedAccount.user_id == user.id)
        ).user.email == "developer@example.test"
        assert conversation.user.email == "developer@example.test"
        assert session.scalar(
            select(UserSettings).where(UserSettings.user_id == user.id)
        ) is not None
        assert "access_token" not in ConnectedAccount.__table__.columns
        assert "refresh_token" not in ConnectedAccount.__table__.columns

        session.add(
            ConnectedAccount(
                user_id=user.id,
                provider="google",
                provider_account_id="sample-google-account",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        other_user = User(email="different@example.test")
        session.add(other_user)
        session.flush()
        session.add(
            ConnectedAccount(
                user_id=other_user.id,
                provider="google",
                provider_account_id="sample-google-account",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(Draft(user_id=user.id, status="sent"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
