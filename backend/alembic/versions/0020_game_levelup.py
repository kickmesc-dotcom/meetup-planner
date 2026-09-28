"""GHG10 Э3 — уведомление о левел-апе в профиле.

Задание: «когда пользователь достиг левел-апа по рангу, у него в профиле
появляется уведомление (какой сейчас ранг, какой был раньше, какие возможности
открылись)». Это ЕДИНСТВЕННОЕ игровое состояние, которое нельзя вывести из `xp`:
уровень/ранг/престиж считаются функцией от опыта, а «уведомление показано»
зависит от того, посмотрел ли юзер профиль.

Поэтому две nullable-колонки на `game_profiles`:

* `pending_level_up_from` — с какого уровня был подъём (None = уведомления нет);
* `pending_level_up_to` — до какого уровня. Если начисление закрыло несколько
  уровней разом — диапазон расширяется (`from` остаётся самым ранним).

Колонки nullable и без server_default: у существующих профилей уведомления нет,
апгрейд безопасен для уже задеплоенной (пустой) таблицы.

Revision ID: 0020_game_levelup
Revises: 0019_game_counters
Create Date: 2026-09-28
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_game_levelup"
down_revision: str | Sequence[str] | None = "0019_game_counters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "game_profiles",
        sa.Column("pending_level_up_from", sa.Integer(), nullable=True),
    )
    op.add_column(
        "game_profiles",
        sa.Column("pending_level_up_to", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("game_profiles", "pending_level_up_to")
    op.drop_column("game_profiles", "pending_level_up_from")
