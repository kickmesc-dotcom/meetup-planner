"""weekly_chukhan + meeting_reminders

Revision ID: 0002_chukhan_reminders
Revises: 0001_initial
Create Date: 2026-05-09

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_chukhan_reminders"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weekly_chukhan",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("week_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "weights_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("tg_message_id", sa.BigInteger()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("week_start", name="uq_weekly_chukhan_week"),
    )
    op.create_index("ix_weekly_chukhan_week", "weekly_chukhan", ["week_start"])

    op.create_table(
        "meeting_reminders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "meeting_id",
            sa.BigInteger(),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("offset_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("meeting_id", "offset_minutes", name="uq_meeting_reminder"),
    )
    op.create_index("ix_reminder_due_at", "meeting_reminders", ["due_at"])


def downgrade() -> None:
    op.drop_index("ix_reminder_due_at", table_name="meeting_reminders")
    op.drop_table("meeting_reminders")
    op.drop_index("ix_weekly_chukhan_week", table_name="weekly_chukhan")
    op.drop_table("weekly_chukhan")
