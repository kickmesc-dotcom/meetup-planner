"""poll.tg_poll_id

Revision ID: 0003_poll_tg_id
Revises: 0002_chukhan_reminders
Create Date: 2026-05-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_poll_tg_id"
down_revision: str | Sequence[str] | None = "0002_chukhan_reminders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("polls", sa.Column("tg_poll_id", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_polls_tg_poll_id", "polls", ["tg_poll_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_polls_tg_poll_id", table_name="polls")
    op.drop_column("polls", "tg_poll_id")
