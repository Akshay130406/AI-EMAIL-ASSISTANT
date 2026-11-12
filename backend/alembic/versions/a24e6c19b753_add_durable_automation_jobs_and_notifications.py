"""Add durable automation jobs and notifications.

Revision ID: a24e6c19b753
Revises: 8f1e2c4a6b90
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a24e6c19b753"
down_revision: Union[str, None] = "8f1e2c4a6b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "automation_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), server_default="1440", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('gmail_sync', 'daily_briefing', 'follow_up_reminder')",
            name="ck_automation_kind",
        ),
        sa.CheckConstraint(
            "interval_minutes BETWEEN 15 AND 10080",
            name="ck_automation_interval",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "kind", name="uq_automation_user_kind"),
    )
    op.create_index(
        op.f("ix_automation_rules_user_id"),
        "automation_rules",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_automation_due",
        "automation_rules",
        ["enabled", "next_run_at"],
        unique=False,
    )
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("automation_id", sa.Uuid(), nullable=True),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=60), nullable=True),
        sa.Column("result_summary", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "job_type IN ('gmail_sync', 'daily_briefing', 'follow_up_reminder')",
            name="ck_background_job_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_background_job_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts BETWEEN 1 AND 5",
            name="ck_background_job_attempts",
        ),
        sa.ForeignKeyConstraint(["automation_id"], ["automation_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_background_job_idempotency"
        ),
    )
    op.create_index(
        op.f("ix_background_jobs_user_id"),
        "background_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_background_job_claim",
        "background_jobs",
        ["status", "available_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_background_job_user_created",
        "background_jobs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_job_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('gmail_sync', 'daily_briefing', 'follow_up_reminder', 'job')",
            name="ck_notification_kind",
        ),
        sa.ForeignKeyConstraint(["source_job_id"], ["background_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_job_id"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_notification_idempotency"
        ),
    )
    op.create_index(
        op.f("ix_notifications_user_id"),
        "notifications",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_user_created",
        "notifications",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notification_user_read",
        "notifications",
        ["user_id", "read_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notification_user_read", table_name="notifications")
    op.drop_index("ix_notification_user_created", table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_background_job_user_created", table_name="background_jobs")
    op.drop_index("ix_background_job_claim", table_name="background_jobs")
    op.drop_index(op.f("ix_background_jobs_user_id"), table_name="background_jobs")
    op.drop_table("background_jobs")
    op.drop_index("ix_automation_due", table_name="automation_rules")
    op.drop_index(op.f("ix_automation_rules_user_id"), table_name="automation_rules")
    op.drop_table("automation_rules")
