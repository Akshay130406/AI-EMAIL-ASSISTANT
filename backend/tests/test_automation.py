from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models import (
    AutomationRule,
    BackgroundJob,
    Email,
    Notification,
    User,
)
from app.services import automation as automation_service
from app.services import job_worker
from tests.helpers import get_development_user


def _create_rule(session, user_id, *, kind="gmail_sync", enabled=False, due=False):
    now = automation_service.utc_now()
    rule = AutomationRule(
        user_id=user_id,
        kind=kind,
        enabled=enabled,
        interval_minutes=60,
        next_run_at=now - timedelta(minutes=5) if due else now + timedelta(hours=1),
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def test_automation_api_creates_runs_and_tracks_durable_jobs(
    client, db_session_factory
):
    created = client.post(
        "/api/automations",
        json={"kind": "gmail_sync", "interval_minutes": 60, "enabled": True},
    )
    assert created.status_code == 201
    automation_id = created.json()["id"]
    duplicate = client.post(
        "/api/automations",
        json={"kind": "gmail_sync", "interval_minutes": 60, "enabled": True},
    )
    assert duplicate.status_code == 409

    queued = client.post(f"/api/automations/{automation_id}/run")
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"
    jobs = client.get("/api/jobs")
    assert jobs.status_code == 200
    assert jobs.json()["total"] == 1
    assert jobs.json()["items"][0]["id"] == queued.json()["id"]

    cancelled = client.post(f"/api/jobs/{queued.json()['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.post(f"/api/jobs/{queued.json()['id']}/cancel").status_code == 409

    with db_session_factory() as session:
        job = session.get(BackgroundJob, UUID(queued.json()["id"]))
        assert job is not None
        assert job.status == "cancelled"


def test_automation_and_job_endpoints_are_user_scoped(
    client, db_session_factory
):
    with db_session_factory() as session:
        owner = User(email="automation-owner@example.test")
        session.add(owner)
        session.flush()
        rule = _create_rule(session, owner.id)
        job = BackgroundJob(
            user_id=owner.id,
            automation_id=rule.id,
            job_type="gmail_sync",
            idempotency_key="foreign-job",
            payload={},
        )
        notification = Notification(
            user_id=owner.id,
            kind="gmail_sync",
            title="Private",
            message="Private notification",
            data={},
            idempotency_key="foreign-notification",
        )
        session.add_all([job, notification])
        session.commit()
        automation_id, job_id, notification_id = rule.id, job.id, notification.id

    assert client.get("/api/automations").json() == []
    assert client.get("/api/jobs").json()["total"] == 0
    assert client.get("/api/notifications").json()["total"] == 0
    assert client.post(f"/api/automations/{automation_id}/run").status_code == 404
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 404
    assert client.patch(
        f"/api/notifications/{notification_id}",
        json={"read": True},
    ).status_code == 404


def test_due_automations_are_queued_once_and_advance_schedule(
    client, db_session_factory
):
    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        rule = _create_rule(session, user.id, enabled=True, due=True)
        rule_id = rule.id

    now = automation_service.utc_now()
    with db_session_factory() as session:
        assert automation_service.enqueue_due_automations(session, now=now) == 1
    with db_session_factory() as session:
        assert automation_service.enqueue_due_automations(session, now=now) == 0
        rule = session.get(AutomationRule, rule_id)
        jobs = list(session.scalars(select(BackgroundJob)))
        assert rule is not None
        assert automation_service._aware(rule.next_run_at) > now
        assert len(jobs) == 1
        assert jobs[0].status == "queued"
        assert jobs[0].idempotency_key.startswith(f"scheduled:{rule_id}:")


def test_worker_claims_completes_and_notifies_once(
    client, db_session_factory, monkeypatch
):
    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        rule = _create_rule(session, user.id, kind="follow_up_reminder")
        job = automation_service.request_manual_run(session, user, rule.id)
        job_id = job.id

    claim = job_worker.claim_next_job(db_session_factory)
    assert claim is not None
    assert claim[0] == job_id
    with db_session_factory() as session:
        job = session.get(BackgroundJob, job_id)
        assert job is not None
        assert job.status == "running"
        assert job.attempts == 1

    monkeypatch.setattr(
        job_worker,
        "_run_job",
        lambda session, claimed_job, current_user: (
            "Follow-up review completed.",
            {"review_count": 2, "email_ids": []},
        ),
    )
    assert job_worker.process_claimed_job(db_session_factory, *claim) is True
    with db_session_factory() as session:
        job = session.get(BackgroundJob, job_id)
        notification = session.scalar(
            select(Notification).where(Notification.source_job_id == job_id)
        )
        assert job is not None
        assert job.status == "succeeded"
        assert notification is not None
        assert notification.data["review_count"] == 2
        assert notification.user_id == user.id


def test_worker_retries_transient_errors_with_bounded_backoff(
    client, db_session_factory, monkeypatch
):
    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        rule = _create_rule(session, user.id)
        job = automation_service.request_manual_run(session, user, rule.id)
        job_id = job.id
    claim = job_worker.claim_next_job(db_session_factory)
    assert claim is not None

    from app.services.gmail import GmailAPIUnavailable

    def fail(session, claimed_job, current_user):
        raise GmailAPIUnavailable

    monkeypatch.setattr(job_worker, "_run_job", fail)
    assert job_worker.process_claimed_job(db_session_factory, *claim) is False
    with db_session_factory() as session:
        job = session.get(BackgroundJob, job_id)
        assert job is not None
        assert job.status == "queued"
        assert job.last_error_code == "GMAIL_TEMPORARILY_UNAVAILABLE"
        assert automation_service._aware(job.available_at) > automation_service.utc_now()


def test_follow_up_only_flags_latest_incoming_messages_without_later_replies(
    client, db_session_factory
):
    from datetime import timedelta

    user = get_development_user(db_session_factory)
    received_at = automation_service.utc_now() - timedelta(days=3)
    with db_session_factory() as session:
        session.add_all(
            [
                Email(
                    user_id=user.id,
                    source="gmail",
                    external_message_id="earlier-incoming",
                    thread_id="needs-follow-up",
                    sender="sender@example.test",
                    recipients=[],
                    subject="Earlier incoming",
                    is_sent=False,
                    received_at=received_at - timedelta(days=1),
                ),
                Email(
                    user_id=user.id,
                    source="gmail",
                    external_message_id="earlier-reply",
                    thread_id="needs-follow-up",
                    sender="user@example.test",
                    recipients=[],
                    subject="Earlier reply",
                    is_sent=True,
                    received_at=received_at - timedelta(hours=12),
                ),
                Email(
                    user_id=user.id,
                    source="gmail",
                    external_message_id="latest-incoming",
                    thread_id="needs-follow-up",
                    sender="sender@example.test",
                    recipients=[],
                    subject="Latest incoming",
                    is_sent=False,
                    received_at=received_at,
                ),
                Email(
                    user_id=user.id,
                    source="gmail",
                    external_message_id="replied-incoming",
                    thread_id="already-replied",
                    sender="sender@example.test",
                    recipients=[],
                    subject="Needs no reminder",
                    is_sent=False,
                    received_at=received_at,
                ),
                Email(
                    user_id=user.id,
                    source="gmail",
                    external_message_id="later-reply",
                    thread_id="already-replied",
                    sender="user@example.test",
                    recipients=[],
                    subject="Later reply",
                    is_sent=True,
                    received_at=received_at + timedelta(minutes=1),
                ),
            ]
        )
        session.commit()
        data = job_worker._follow_up_data(session, user.id)

    assert data["review_count"] == 1
    with db_session_factory() as session:
        email = session.get(Email, UUID(data["email_ids"][0]))
        assert email is not None
        assert email.external_message_id == "latest-incoming"


def test_queue_limits_prevent_unbounded_user_jobs(client, db_session_factory):
    user = get_development_user(db_session_factory)
    with db_session_factory() as session:
        rule = _create_rule(session, user.id)
        rule_id = rule.id
        for index in range(automation_service.MAX_PENDING_JOBS_PER_USER):
            session.add(
                BackgroundJob(
                    user_id=user.id,
                    automation_id=rule.id,
                    job_type=rule.kind,
                    idempotency_key=f"queued-{index}",
                    payload={},
                )
            )
        session.commit()
    response = client.post(f"/api/automations/{rule_id}/run")
    assert response.status_code == 429
