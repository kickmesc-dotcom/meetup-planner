"""GHG10 Э15 — музыкальная предложка (GHG8 H.7).

Две таблицы:

* `music_tracks` — предложенный трек: только ссылка (`kind='link'`) или Telegram
  `file_id` (`kind='audio'`). Файлы физически НЕ храним: хост слабый.
* `music_selections` — выпущенные подборки (история для админки) и неудачные
  попытки публикации (недобор) — по ним планировщик решает, когда повторить.

Revision ID: 0024_music_suggestions
Revises: 0023_game_voice_tasks
Create Date: 2026-09-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_music_suggestions"
down_revision: str | Sequence[str] | None = "0023_game_voice_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "music_selections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column("track_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_music_selections_created", "music_selections", ["created_at"]
    )

    op.create_table(
        "music_tracks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("file_id", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("performer", sa.Text(), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=12), nullable=False, server_default="pool"
        ),
        sa.Column(
            "selection_id",
            sa.BigInteger(),
            sa.ForeignKey("music_selections.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_music_tracks_pool", "music_tracks", ["status", "added_at"])
    op.create_index("ix_music_tracks_user", "music_tracks", ["user_id", "added_at"])


def downgrade() -> None:
    op.drop_index("ix_music_tracks_user", table_name="music_tracks")
    op.drop_index("ix_music_tracks_pool", table_name="music_tracks")
    op.drop_table("music_tracks")
    op.drop_index("ix_music_selections_created", table_name="music_selections")
    op.drop_table("music_selections")
