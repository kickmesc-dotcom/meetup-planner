"""GHG10 Э16 — мьюзик-гейм «угадай, кто предложил трек» (GHG8 H.8).

Одна таблица `music_game_rounds`: выбранный трек, верный автор, карта «индекс
варианта опроса → user_id», список угадавших и состояние раунда. Трек-источник
связан `ON DELETE SET NULL`, чтобы удаление трека админом не рвало историю.
Память об использованных треках — сам факт записи в этой таблице.

Revision ID: 0025_music_game_rounds
Revises: 0024_music_suggestions
Create Date: 2026-09-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025_music_game_rounds"
down_revision: str | Sequence[str] | None = "0024_music_suggestions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "music_game_rounds",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "track_id",
            sa.BigInteger(),
            sa.ForeignKey("music_tracks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "correct_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column("tg_poll_id", sa.String(length=64), nullable=True, unique=True),
        sa.Column(
            "option_user_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "correct_voter_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_music_game_rounds_open", "music_game_rounds", ["chat_id", "closed_at"]
    )
    op.create_index(
        "ix_music_game_rounds_track", "music_game_rounds", ["track_id"]
    )
    op.create_index(
        "ix_music_game_rounds_created", "music_game_rounds", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_music_game_rounds_created", table_name="music_game_rounds")
    op.drop_index("ix_music_game_rounds_track", table_name="music_game_rounds")
    op.drop_index("ix_music_game_rounds_open", table_name="music_game_rounds")
    op.drop_table("music_game_rounds")
