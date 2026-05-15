"""chat_messages table

Revision ID: 0005_chat_messages
Revises: 0004_admin_config
Create Date: 2026-05-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_chat_messages"
down_revision: str | Sequence[str] | None = "0004_admin_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", "tg_message_id", name="uq_chat_msg"),
    )
    op.create_index(
        "ix_chat_msg_user_sent", "chat_messages", ["user_id", "sent_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_chat_msg_user_sent", table_name="chat_messages")
    op.drop_table("chat_messages")
