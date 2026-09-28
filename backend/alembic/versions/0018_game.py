"""GHG10 — геймификация: опыт, уровни, ранги, ачивки.

Шесть новых таблиц, ничего не меняем в существующих:

- `game_profiles` — игровой профиль (единственный источник правды по `xp`;
  уровень/ранг/престиж выводятся из него в коде).
- `xp_daily` — дневная история начислений (агрегат user+day+event). «Обнуление в
  00:00» из задания — фильтр по дате, не удаление.
- `xp_grants` — маркеры идемпотентности для лимитированных начислений
  (неделя/год/раз), уникальный индекс на (user_id, idem_key).
- `user_achievements` — собранные ачивки, уникально на (user_id, code).
- `chat_activity_daily` — счётчик сообщений по дням (durable, в отличие от
  `chat_messages` с ретеншеном 7 дней).
- `game_holidays` — пул праздников (месяц+день, ежегодные).

Все таблицы безопасны: только `create_table`, без backfill и NOT NULL без
default на существующих данных. Откат — обратный `drop_table`, порядок
обратный из-за FK.

Revision ID: 0018_game
Revises: 0017_avatar_stable
Create Date: 2026-09-28
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_game"
down_revision: str | Sequence[str] | None = "0017_avatar_stable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_profiles",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("custom_name", sa.Text(), nullable=True),
        sa.Column("custom_rank_title", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "xp_daily",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("event", sa.String(length=32), primary_key=True),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_xp_daily_user_day", "xp_daily", ["user_id", "day"])

    op.create_table(
        "xp_grants",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idem_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_xp_grant_key", "xp_grants", ["user_id", "idem_key"], unique=True
    )

    op.create_table(
        "user_achievements",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column(
            "unlocked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_user_achievement", "user_achievements", ["user_id", "code"], unique=True
    )
    op.create_index(
        "ix_user_achievement_unlocked", "user_achievements", ["unlocked_at"]
    )

    op.create_table(
        "chat_activity_daily",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("messages", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_chat_activity_day", "chat_activity_daily", ["day"])

    op.create_table(
        "game_holidays",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("day", sa.SmallInteger(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("month", "day", name="uq_game_holiday_md"),
    )


def downgrade() -> None:
    op.drop_table("game_holidays")
    op.drop_index("ix_chat_activity_day", table_name="chat_activity_daily")
    op.drop_table("chat_activity_daily")
    op.drop_index("ix_user_achievement_unlocked", table_name="user_achievements")
    op.drop_index("uq_user_achievement", table_name="user_achievements")
    op.drop_table("user_achievements")
    op.drop_index("ix_xp_grant_key", table_name="xp_grants")
    op.drop_table("xp_grants")
    op.drop_index("ix_xp_daily_user_day", table_name="xp_daily")
    op.drop_table("xp_daily")
    op.drop_table("game_profiles")
