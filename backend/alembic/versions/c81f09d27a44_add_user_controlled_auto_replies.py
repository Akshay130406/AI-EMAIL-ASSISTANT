"""Add explicitly controlled automatic email replies."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c81f09d27a44"
down_revision: Union[str, None] = "a24e6c19b753"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("emails", sa.Column("has_attachments", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_table(
        "auto_reply_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("automatic_sending_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("daily_limit", sa.Integer(), server_default="5", nullable=False),
        sa.Column("reply_required_only", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("exclude_sensitive", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("allowed_senders", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("blocked_senders", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("include_keywords", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("exclude_keywords", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.CheckConstraint("daily_limit BETWEEN 1 AND 50", name="ck_auto_reply_daily_limit"),
        sa.CheckConstraint("interval_minutes BETWEEN 15 AND 1440", name="ck_auto_reply_interval"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_auto_reply_settings_user"),
    )
    op.create_index(op.f("ix_auto_reply_settings_user_id"), "auto_reply_settings", ["user_id"], unique=False)
    op.create_index("ix_auto_reply_due", "auto_reply_settings", ["enabled", "next_run_at"], unique=False)

    op.create_table(
        "auto_reply_activities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="processing", nullable=False),
        sa.Column("reason_code", sa.String(length=60), nullable=True),
        sa.Column("gmail_draft_id", sa.String(length=255), nullable=True),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.CheckConstraint("status IN ('processing', 'draft_created', 'sent', 'skipped', 'failed', 'unknown')", name="ck_auto_reply_activity_status"),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "email_id", name="uq_auto_reply_activity_email"),
    )
    op.create_index(op.f("ix_auto_reply_activities_user_id"), "auto_reply_activities", ["user_id"], unique=False)
    op.create_index("ix_auto_reply_activity_user_created", "auto_reply_activities", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_auto_reply_activity_user_created", table_name="auto_reply_activities")
    op.drop_index(op.f("ix_auto_reply_activities_user_id"), table_name="auto_reply_activities")
    op.drop_table("auto_reply_activities")
    op.drop_index("ix_auto_reply_due", table_name="auto_reply_settings")
    op.drop_index(op.f("ix_auto_reply_settings_user_id"), table_name="auto_reply_settings")
    op.drop_table("auto_reply_settings")
    op.drop_column("emails", "has_attachments")
