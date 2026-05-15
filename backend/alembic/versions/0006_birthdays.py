"""birthdays + birthday_notifications

Revision ID: 0006_birthdays
Revises: 0005_chat_messages
Create Date: 2026-05-15
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_birthdays"
down_revision: str | Sequence[str] | None = "0005_chat_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "birthdays",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("bday", sa.Date(), nullable=True),
        sa.Column(
            "year_known", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "remind_month", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "remind_week", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "remind_day", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "remind_on_day", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "remind_hint_week",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "birthday_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "year", "kind", name="uq_birthday_notif"),
    )


def downgrade() -> None:
    op.drop_table("birthday_notifications")
    op.drop_table("birthdays")
