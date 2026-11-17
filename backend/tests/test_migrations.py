from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy import inspect
from alembic.runtime.migration import MigrationContext


def test_initial_migration_creates_schema_and_is_current(tmp_path, monkeypatch):
    database_path = tmp_path / "migration-test.sqlite3"
    monkeypatch.setenv(
        "DATABASE_URL",
        URL.create("sqlite", database=str(database_path)).render_as_string(
            hide_password=False
        ),
    )
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(config, "head")

    engine = create_engine(
        URL.create("sqlite", database=str(database_path)),
    )
    try:
        inspector: Inspector = inspect(engine)
        assert {
            "users",
            "connected_accounts",
            "emails",
            "drafts",
            "conversations",
            "conversation_messages",
            "user_settings",
            "automation_rules",
            "background_jobs",
            "notifications",
            "user_sessions",
            "oauth_transactions",
            "auto_reply_settings",
            "auto_reply_activities",
            "alembic_version",
        }.issubset(set(inspector.get_table_names()))
        assert {
            "email_address",
            "access_token_encrypted",
            "refresh_token_encrypted",
            "token_expires_at",
            "granted_scopes",
            "gmail_history_id",
            "gmail_history_page_token",
            "gmail_pending_message_ids",
            "gmail_pending_history_id",
            "last_synced_at",
        }.issubset(
            {column["name"] for column in inspector.get_columns("connected_accounts")}
        )
        assert {"source", "html_body", "is_sent", "has_attachments"}.issubset(
            {column["name"] for column in inspector.get_columns("emails")}
        )
        draft_columns = {
            column["name"]: column for column in inspector.get_columns("drafts")
        }
        assert {
            "recipients",
            "cc",
            "bcc",
            "gmail_draft_id",
            "gmail_message_id",
            "send_status",
        }.issubset(draft_columns)
        assert {
            constraint["name"]
            for constraint in inspector.get_check_constraints("drafts")
        }.issuperset({"ck_draft_status", "ck_draft_send_status"})
        assert "uq_draft_gmail_draft_id" in {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("drafts")
        }
        assert {
            "ck_automation_kind",
            "ck_automation_interval",
        }.issubset(
            {
                constraint["name"]
                for constraint in inspector.get_check_constraints("automation_rules")
            }
        )
        assert {
            "ck_background_job_type",
            "ck_background_job_status",
            "ck_background_job_attempts",
        }.issubset(
            {
                constraint["name"]
                for constraint in inspector.get_check_constraints("background_jobs")
            }
        )

        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        assert current == ScriptDirectory.from_config(config).get_current_head()
    finally:
        engine.dispose()
