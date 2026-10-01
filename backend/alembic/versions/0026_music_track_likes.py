"""GHG10 Э17 — лайки трекам выпущенной подборки (задел GHG8 H.8).

Одна таблица `music_track_likes`: (user_id, track_id) с уникальностью — повторный
тап из мини-аппа ничего не дублирует, а `DELETE` снимает лайк. По этим строкам
считается «топ треков недели». Обе ссылки `ON DELETE CASCADE`: без пользователя
или трека лайк смысла не имеет.

Revision ID: 0026_music_track_likes
Revises: 0025_music_game_rounds
Create Date: 2026-09-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_music_track_likes"
down_revision: str | Sequence[str] | None = "0025_music_game_rounds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "music_track_likes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "track_id",
            sa.BigInteger(),
            sa.ForeignKey("music_tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "track_id", name="uq_music_track_like"),
    )
    op.create_index(
        "ix_music_track_likes_track", "music_track_likes", ["track_id"]
    )
    op.create_index("ix_music_track_likes_user", "music_track_likes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_music_track_likes_user", table_name="music_track_likes")
    op.drop_index("ix_music_track_likes_track", table_name="music_track_likes")
    op.drop_table("music_track_likes")
