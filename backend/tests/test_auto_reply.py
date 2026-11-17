from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, func
from pydantic import ValidationError

from app.models import AutoReplyActivity, AutoReplySettings, ConnectedAccount, Draft, Email, User
from app.schemas.auto_reply import AutoReplySettingsUpdate
from app.services import auto_reply, gmail


def _configured_user(session_factory):
    user = User(email="auto-reply@example.test")
    with session_factory() as session:
        session.add(user)
        session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            provider_account_id="auto-reply-subject",
            status="connected",
            email_address="auto-reply@example.test",
            access_token_encrypted="encrypted-test-token",
            granted_scopes=[gmail.GMAIL_COMPOSE_SCOPE],
        )
        settings = AutoReplySettings(
            user_id=user.id,
            enabled=True,
            automatic_sending_enabled=False,
            reply_required_only=False,
            enabled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        email = Email(
            user_id=user.id,
            source="gmail",
            external_message_id="incoming-1",
            thread_id="thread-1",
            sender="Customer <customer@example.test>",
            recipients=["auto-reply@example.test"],
            subject="A new question",
            body="Can you share the public meeting agenda?",
            preview="Can you share the public meeting agenda?",
            is_sent=False,
            received_at=datetime.now(timezone.utc) - timedelta(minutes=3),
        )
        session.add_all([account, settings, email])
        session.commit()
        return user.id, settings.id, account.id, email.id


def _mock_gmail_and_gemini(monkeypatch, send_calls):
    monkeypatch.setattr(auto_reply.gmail, "sync_gmail", lambda *args, **kwargs: {"synced": 0, "incremental": True})
    monkeypatch.setattr(auto_reply.gmail, "build_gmail_service", lambda *args, **kwargs: object())
    monkeypatch.setattr(auto_reply.gmail, "create_remote_gmail_draft", lambda *args, **kwargs: {
        "id": f"remote-draft-{len(send_calls) + 1}",
        "message": {"id": "draft-message", "threadId": "thread-1"},
    })
    monkeypatch.setattr(auto_reply.gmail, "parsed_gmail_draft", lambda message: {"gmail_message_id": "draft-message"})
    monkeypatch.setattr(auto_reply.gmail, "send_remote_gmail_draft", lambda *args, **kwargs: send_calls.append("sent") or {
        "id": f"sent-{len(send_calls)}", "threadId": "thread-1",
    })
    monkeypatch.setattr(auto_reply.ai, "suggest_reply", lambda *args, **kwargs: SimpleNamespace(
        subject="Re: A new question", body="Here is the agenda.",
    ))


def test_auto_reply_defaults_off_and_requires_explicit_send_confirmation(db_session_factory):
    user = User(email="safe-default@example.test")
    with db_session_factory() as session:
        session.add(user)
        session.commit()
        settings = auto_reply.get_settings(session, user)
        assert settings.enabled is False
        assert settings.automatic_sending_enabled is False
        assert settings.exclude_sensitive is True
    with pytest.raises(ValidationError):
        AutoReplySettingsUpdate(automatic_sending_enabled=True)


def test_emergency_off_disables_processing_and_sending(db_session_factory):
    user = User(email="emergency-off@example.test")
    with db_session_factory() as session:
        session.add(user)
        session.commit()
        settings = auto_reply.get_settings(session, user)
        settings.enabled = True
        settings.automatic_sending_enabled = True
        settings.next_run_at = datetime.now(timezone.utc)
        session.commit()
        stopped = auto_reply.emergency_off(session, user)
        assert stopped.enabled is False
        assert stopped.automatic_sending_enabled is False
        assert stopped.next_run_at is None


def test_worker_only_runs_due_explicitly_enabled_accounts(db_session_factory, monkeypatch):
    user = User(email="scheduled-auto-reply@example.test")
    now = datetime.now(timezone.utc)
    with db_session_factory() as session:
        session.add(user)
        session.flush()
        disabled_owner = User(email="disabled-auto-reply@example.test")
        session.add(disabled_owner)
        session.flush()
        disabled = AutoReplySettings(user_id=disabled_owner.id, enabled=False, next_run_at=now - timedelta(minutes=1))
        enabled = AutoReplySettings(
            user_id=user.id,
            enabled=True,
            automatic_sending_enabled=False,
            enabled_at=now - timedelta(hours=1),
            next_run_at=now - timedelta(minutes=1),
        )
        session.add_all([disabled, enabled])
        session.commit()
        enabled_id = enabled.id
    runs = []
    monkeypatch.setattr(auto_reply, "process_user", lambda session, owner, settings: runs.append(settings.id) or 0)
    assert auto_reply.run_due(db_session_factory, now=now) == 0
    assert runs == [enabled_id]
    with db_session_factory() as session:
        next_run = session.get(AutoReplySettings, enabled_id).next_run_at
        next_run = next_run.replace(tzinfo=timezone.utc) if next_run.tzinfo is None else next_run
        assert next_run > now


def test_draft_mode_creates_one_editable_draft_and_is_idempotent(
    db_session_factory, monkeypatch
):
    user_id, settings_id, _account_id, _email_id = _configured_user(db_session_factory)
    sends: list[str] = []
    _mock_gmail_and_gemini(monkeypatch, sends)
    with db_session_factory() as session:
        user = session.get(User, user_id)
        settings = session.get(AutoReplySettings, settings_id)
        assert auto_reply.process_user(session, user, settings) == 1
        assert auto_reply.process_user(session, user, settings) == 0
        activity = session.scalar(select(AutoReplyActivity).where(AutoReplyActivity.user_id == user_id))
        draft = session.scalar(select(Draft).where(Draft.user_id == user_id))
        assert activity.status == "draft_created"
        assert draft.send_status == "not_sent"
        assert sends == []


def test_confirmed_send_mode_obeys_daily_cap_and_pre_send_exclusions(
    db_session_factory, monkeypatch
):
    user_id, settings_id, _account_id, _email_id = _configured_user(db_session_factory)
    sends: list[str] = []
    _mock_gmail_and_gemini(monkeypatch, sends)
    with db_session_factory() as session:
        settings = session.get(AutoReplySettings, settings_id)
        settings.automatic_sending_enabled = True
        settings.daily_limit = 1
        sensitive = Email(
            user_id=user_id,
            source="gmail",
            external_message_id="sensitive-1",
            sender="Customer <other@example.test>",
            subject="Password reset code",
            body="Your verification code is 123456",
            is_sent=False,
            received_at=datetime.now(timezone.utc),
        )
        attachment = Email(
            user_id=user_id,
            source="gmail",
            external_message_id="attachment-1",
            sender="Customer <third@example.test>",
            subject="Agenda attached",
            body="See the document.",
            has_attachments=True,
            is_sent=False,
            received_at=datetime.now(timezone.utc),
        )
        second_replyable = Email(
            user_id=user_id,
            source="gmail",
            external_message_id="incoming-2",
            sender="Another Customer <another@example.test>",
            subject="A second question",
            body="Could you share the meeting time?",
            is_sent=False,
            received_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        )
        session.add_all([sensitive, attachment, second_replyable])
        session.commit()
        user = session.get(User, user_id)
        settings = session.get(AutoReplySettings, settings_id)
        assert auto_reply.process_user(session, user, settings) == 4
        statuses = dict(session.execute(select(AutoReplyActivity.reason_code, func.count()).where(
            AutoReplyActivity.user_id == user_id,
        ).group_by(AutoReplyActivity.reason_code)).all())
        assert sends == ["sent"]
        assert statuses[None] == 1
        assert statuses["sensitive_content"] == 1
        assert statuses["attachment_excluded"] == 1
        assert statuses["daily_limit_reached"] == 1
        sent_activity = session.scalar(select(AutoReplyActivity).where(
            AutoReplyActivity.status == "sent",
            AutoReplyActivity.user_id == user_id,
        ))
        assert sent_activity is not None
