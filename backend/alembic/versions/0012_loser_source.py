"""GHG6 H1 — loser_rolls.source для разделения авто-/ручного cooldown'а.

Раньше `time_until_next_roll` смотрел МАКС rolled_at по всей таблице — авто-лох
крутился каждый день и блокировал ручную рулетку из-за 12-часового cooldown.
Пользовательский сценарий: ручная рулетка независима от автолоха.

Решение: добавляем колонку `source` ('auto' | 'manual') и фильтруем cooldown
только по строкам соответствующего источника. Все существующие строки —
'manual' (до этой миграции автолох писал в ту же таблицу неотличимо от ручной
рулетки; теперь нет смысла «гадать», ретро-разметка нерелевантна для текущего
cooldown — он считается от ПОСЛЕДНЕЙ строки).

Revision ID: 0012_loser_source
Revises: 0011_poll_is_closed
Create Date: 2026-05-25
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_loser_source"
down_revision: str | Sequence[str] | None = "0011_poll_is_closed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default='manual' проставляет существующие строки одним движением;
    # после миграции дропаем server_default — приложение пишет source явно.
    op.add_column(
        "loser_rolls",
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
    )
    op.alter_column("loser_rolls", "source", server_default=None)
    op.create_index(
        "ix_loser_source_rolled_at",
        "loser_rolls",
        ["source", "rolled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_loser_source_rolled_at", table_name="loser_rolls")
    op.drop_column("loser_rolls", "source")
