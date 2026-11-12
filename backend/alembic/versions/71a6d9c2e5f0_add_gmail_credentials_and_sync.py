"""Add encrypted Gmail credentials and synchronization metadata.

Revision ID: 71a6d9c2e5f0
Revises: 2d1f6b8c9a40
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "71a6d9c2e5f0"
down_revision: Union[str, None] = "2d1f6b8c9a40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("connected_accounts") as batch_op:
        batch_op.add_column(sa.Column("email_address", sa.String(length=320), nullable=True))
        batch_op.add_column(sa.Column("access_token_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("refresh_token_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("granted_scopes", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.alter_column("granted_scopes", server_default=None)
        batch_op.add_column(sa.Column("gmail_history_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("gmail_history_page_token", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "gmail_pending_message_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )
        batch_op.alter_column("gmail_pending_message_ids", server_default=None)
        batch_op.add_column(
            sa.Column("gmail_pending_history_id", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_connected_account_user_provider", ["user_id", "provider"]
        )

    with op.batch_alter_table("emails") as batch_op:
        batch_op.drop_constraint("uq_email_external_message", type_="unique")
        batch_op.add_column(
            sa.Column(
                "source",
                sa.String(length=20),
                nullable=False,
                server_default="sample",
            )
        )
        batch_op.add_column(sa.Column("html_body", sa.Text(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_email_external_source",
            ["user_id", "source", "external_message_id"],
        )
        batch_op.create_check_constraint(
            "ck_email_source", "source IN ('sample', 'gmail')"
        )

    with op.batch_alter_table("oauth_transactions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "provider",
                sa.String(length=40),
                nullable=False,
                server_default="google_login",
            )
        )
        batch_op.add_column(sa.Column("user_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_oauth_transactions_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_oauth_transactions_user_id", ["user_id"])


def downgrade() -> None:
    with op.batch_alter_table("oauth_transactions") as batch_op:
        batch_op.drop_index("ix_oauth_transactions_user_id")
        batch_op.drop_constraint(
            "fk_oauth_transactions_user_id_users", type_="foreignkey"
        )
        batch_op.drop_column("user_id")
        batch_op.drop_column("provider")

    with op.batch_alter_table("emails") as batch_op:
        batch_op.drop_constraint("ck_email_source", type_="check")
        batch_op.drop_constraint("uq_email_external_source", type_="unique")
        batch_op.drop_column("html_body")
        batch_op.drop_column("source")
        batch_op.create_unique_constraint(
            "uq_email_external_message", ["user_id", "external_message_id"]
        )

    with op.batch_alter_table("connected_accounts") as batch_op:
        batch_op.drop_constraint(
            "uq_connected_account_user_provider", type_="unique"
        )
        batch_op.drop_column("last_synced_at")
        batch_op.drop_column("gmail_pending_history_id")
        batch_op.drop_column("gmail_pending_message_ids")
        batch_op.drop_column("gmail_history_page_token")
        batch_op.drop_column("gmail_history_id")
        batch_op.drop_column("granted_scopes")
        batch_op.drop_column("token_expires_at")
        batch_op.drop_column("refresh_token_encrypted")
        batch_op.drop_column("access_token_encrypted")
        batch_op.drop_column("email_address")
