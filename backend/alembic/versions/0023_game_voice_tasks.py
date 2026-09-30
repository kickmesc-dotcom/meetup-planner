"""GHG10 Э14 — голосовые задания: окно сбора, сводка, опциональный опрос.

Новая фича не помещается в существующие таблицы:

* `game_voice_tasks` — поставленное задание: текст, сообщение-якорь (ответы
  принимаются реплаем на него), дедлайн, пометка о сводке и опциональный опрос
  с картой «индекс варианта → user_id».
* `game_voice_submissions` — сданные голосовые. Храним только `file_id` и
  метаданные: хост слабый, физически держать аудио нельзя. Уникальность
  `(task_id, user_id)` = один вариант на участника.

Revision ID: 0023_game_voice_tasks
Revises: 0022_game_journal_prompts
Create Date: 2026-09-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023_game_voice_tasks"
down_revision: str | Sequence[str] | None = "0022_game_journal_prompts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_voice_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("reward", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "poll_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("tg_poll_id", sa.String(length=64), nullable=True, unique=True),
        sa.Column(
            "poll_user_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "winner_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("outcome", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_game_voice_tasks_open",
        "game_voice_tasks",
        ["chat_id", "closed_at", "expires_at"],
    )

    op.create_table(
        "game_voice_submissions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("game_voice_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "task_id", "user_id", name="uq_game_voice_submission"
        ),
    )
    op.create_index(
        "ix_game_voice_submissions_task",
        "game_voice_submissions",
        ["task_id", "submitted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_game_voice_submissions_task", table_name="game_voice_submissions"
    )
    op.drop_table("game_voice_submissions")
    op.drop_index("ix_game_voice_tasks_open", table_name="game_voice_tasks")
    op.drop_table("game_voice_tasks")
