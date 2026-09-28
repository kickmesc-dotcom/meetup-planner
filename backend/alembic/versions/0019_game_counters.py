"""GHG10 — счётчики ачивок + дефолтный праздник.

Два независимых шага:

1. `achievement_counters` — накопители для ачивок, у которых нет источника в
   существующих таблицах (ответы боту, посты с реакциями, мёртвые посты).
   Остальные трекеры считают по `loser_rolls` / `weekly_chukhan` / `polls` /
   `availability_ranges` / `xp_grants` — дублировать их счётчиками не нужно.
2. Дефолтный праздник — «Новый год» (1 января) в `game_holidays`. Задание:
   «в настройки добавим пул праздников, по умолчанию там только новый год».
   Пустая таблица = фича молча ничего не делает, поэтому сидим один раз.

Никаких изменений в существующих таблицах.

Revision ID: 0019_game_counters
Revises: 0018_game
Create Date: 2026-09-28
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_game_counters"
down_revision: str | Sequence[str] | None = "0018_game"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_HOLIDAY = (1, 1, "🎉 С Новым годом, шестёрка! Начинаем год с чистой экспы.")


def upgrade() -> None:
    op.create_table(
        "achievement_counters",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("code", sa.String(length=48), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Дефолтный пул праздников. `enabled=true`, автор — NULL (системная запись).
    month, day, message = _DEFAULT_HOLIDAY
    holidays = sa.table(
        "game_holidays",
        sa.column("month", sa.SmallInteger),
        sa.column("day", sa.SmallInteger),
        sa.column("message", sa.Text),
        sa.column("enabled", sa.Boolean),
        sa.column("created_by_user_id", sa.BigInteger),
    )
    op.execute(
        holidays.insert().values(
            month=month, day=day, message=message, enabled=True,
            created_by_user_id=None,
        )
    )


def downgrade() -> None:
    op.drop_table("achievement_counters")
    month, day, _ = _DEFAULT_HOLIDAY
    op.execute(
        sa.text(
            "DELETE FROM game_holidays "
            "WHERE month = :m AND day = :d AND created_by_user_id IS NULL"
        ).bindparams(m=month, d=day)
    )
