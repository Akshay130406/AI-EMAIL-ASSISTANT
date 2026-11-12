"""Add server-side sessions and OAuth transactions.

Revision ID: 2d1f6b8c9a40
Revises: 860675e271af
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2d1f6b8c9a40"
down_revision: Union[str, None] = "860675e271af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("connected_accounts") as batch_op:
        batch_op.drop_constraint("uq_connected_account_provider", type_="unique")
        batch_op.create_unique_constraint(
            "uq_connected_account_identity", ["provider", "provider_account_id"]
        )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_token_hash"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])
    op.create_index(
        "ix_user_sessions_user_expires", "user_sessions", ["user_id", "expires_at"]
    )

    op.create_table(
        "oauth_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index(
        "ix_oauth_transactions_expires_at", "oauth_transactions", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_oauth_transactions_expires_at", table_name="oauth_transactions")
    op.drop_table("oauth_transactions")
    op.drop_index("ix_user_sessions_user_expires", table_name="user_sessions")
    op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")

    with op.batch_alter_table("connected_accounts") as batch_op:
        batch_op.drop_constraint("uq_connected_account_identity", type_="unique")
        batch_op.create_unique_constraint(
            "uq_connected_account_provider",
            ["user_id", "provider", "provider_account_id"],
        )
