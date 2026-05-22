"""GHG6 E6 — game_nominations + polls.kind/game_nomination_id + meetings.tag.

Лимит «10 активных номинаций» проверяется на уровне сервиса, не БД — так
soft-deleted строки можно «реанимировать» (restore вместо ре-insert при
повторном добавлении одноимённой игры).

Revision ID: 0010_games_nominations
Revises: 0009_bot_pause
Create Date: 2026-05-22
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_games_nominations"
down_revision: str | Sequence[str] | None = "0009_bot_pause"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_nominations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("added_by_tg_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_game_nomination_active", "game_nominations", ["removed_at"]
    )

    op.add_column(
        "polls", sa.Column("kind", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "polls",
        sa.Column("game_nomination_id", sa.BigInteger(), nullable=True),
    )

    op.add_column(
        "meetings", sa.Column("tag", sa.String(length=16), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("meetings", "tag")
    op.drop_column("polls", "game_nomination_id")
    op.drop_column("polls", "kind")
    op.drop_index("ix_game_nomination_active", table_name="game_nominations")
    op.drop_table("game_nominations")
