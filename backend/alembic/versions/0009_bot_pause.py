"""bot_pause — глобальная пауза публикаций бота (E11, GHG6)

При паузе все master-toggles (reminders/loser/phrases/avatars/birthdays/
chukhan/bot_reactions) принудительно выставляются в false. По истечении
`ends_at` (или ручном снятии) — состояние восстанавливается из
`settings_snapshot`. В любой момент существует не более одной активной строки
(partial unique index на (1) WHERE ended_at IS NULL).

Revision ID: 0009_bot_pause
Revises: 0008_worm_assignments
Create Date: 2026-05-22
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009_bot_pause"
down_revision: str | Sequence[str] | None = "0008_worm_assignments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_pause",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by_tg_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "reason",
            sa.String(length=32),
            nullable=False,
            server_default="manual_admin",
        ),
        sa.Column(
            "settings_snapshot",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_bot_pause_started", "bot_pause", ["started_at"])
    op.execute(
        "CREATE UNIQUE INDEX uq_bot_pause_active_singleton "
        "ON bot_pause ((1)) WHERE ended_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_bot_pause_active_singleton")
    op.drop_index("ix_bot_pause_started", table_name="bot_pause")
    op.drop_table("bot_pause")
