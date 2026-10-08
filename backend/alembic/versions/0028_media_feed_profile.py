"""GHG11(10) — осмысленные реакции на медиа и «последняя активность» в профиле.

Две независимые, но связанные по смыслу правки:

1. `game_media_posts` учится хранить ТИП медиа, число файлов в подборке,
   `file_id` миниатюры и саму реакцию бота (эмодзи и/или фразу из пула). До
   этого лента знала лишь факт «бот отреагировал на медиа (кто-то)» — по такой
   строке нельзя было понять ни что за медиа, ни чем именно бот отреагировал.
   Теперь запись поста сама становится источником записи ленты (`feed.py`,
   вид `media`), а миниатюра отдаётся через `/api/media/{post_id}`.

2. `game_profiles.last_app_seen_at` — когда участник последний раз открывал
   мини-апп. Пишется best-effort из `/api/me` (`services/game/presence.py`) и
   показывается в чужом профиле, если участник не выключил это у себя
   (`ui.show_last_seen`, по умолчанию включено).

Revision ID: 0028_media_feed_profile
Revises: 0027_app_notifications
Create Date: 2026-10-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028_media_feed_profile"
down_revision: str | Sequence[str] | None = "0027_app_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "game_media_posts",
        sa.Column("media_type", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "game_media_posts",
        sa.Column("media_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "game_media_posts",
        sa.Column("preview_file_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "game_media_posts",
        sa.Column("reaction_emoji", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "game_media_posts",
        sa.Column("reaction_phrase", sa.Text(), nullable=True),
    )
    op.add_column(
        "game_media_posts",
        sa.Column("reacted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Лента читает «реакции бота» свежими сверху — индекс по моменту реакции.
    op.create_index(
        "ix_game_media_reacted", "game_media_posts", ["reacted_at"]
    )
    op.add_column(
        "game_profiles",
        sa.Column("last_app_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("game_profiles", "last_app_seen_at")
    op.drop_index("ix_game_media_reacted", table_name="game_media_posts")
    op.drop_column("game_media_posts", "reacted_at")
    op.drop_column("game_media_posts", "reaction_phrase")
    op.drop_column("game_media_posts", "reaction_emoji")
    op.drop_column("game_media_posts", "preview_file_id")
    op.drop_column("game_media_posts", "media_count")
    op.drop_column("game_media_posts", "media_type")
