"""Add Gmail draft support and sent message tracking.

Revision ID: 8f1e2c4a6b90
Revises: 71a6d9c2e5f0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8f1e2c4a6b90"
down_revision: Union[str, None] = "71a6d9c2e5f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("emails") as batch_op:
        batch_op.add_column(
            sa.Column("is_sent", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("drafts") as batch_op:
        batch_op.add_column(
            sa.Column("recipients", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("cc", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("bcc", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(sa.Column("gmail_draft_id", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("gmail_message_id", sa.String(255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "send_status",
                sa.String(20),
                nullable=False,
                server_default="not_sent",
            )
        )
        batch_op.create_check_constraint(
            "ck_draft_send_status",
            "send_status IN ('not_sent', 'sending', 'sent', 'unknown', 'failed')",
        )
        batch_op.create_unique_constraint(
            "uq_draft_gmail_draft_id", ["gmail_draft_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("drafts") as batch_op:
        batch_op.drop_constraint("uq_draft_gmail_draft_id", type_="unique")
        batch_op.drop_constraint("ck_draft_send_status", type_="check")
        batch_op.drop_column("send_status")
        batch_op.drop_column("gmail_message_id")
        batch_op.drop_column("gmail_draft_id")
        batch_op.drop_column("bcc")
        batch_op.drop_column("cc")
        batch_op.drop_column("recipients")
    with op.batch_alter_table("emails") as batch_op:
        batch_op.drop_column("is_sent")
