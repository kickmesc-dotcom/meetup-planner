"""GHG10 Э13 — игровой журнал (сводка + поминовения) и случайные события.

Три фичи из списка пожеланий не помещались ни в одну существующую таблицу:

* **Сводка.** Чтобы бот не спамил анонсами, включённый режим сводки должен
  где-то копить события до ближайшего окна. `game_journal` — та самая очередь:
  `sent_at IS NULL` = «в очереди».
* **Поминовения.** «Три недели молчания» требуют durable-памяти о человеке, а
  `chat_messages` чистится через 7 дней. Отдельная строка журнала с
  `subject_user_id` и `resolved_at` держит поминовение ОТКРЫТЫМ, пока человек
  не вернётся — именно её закрытие и вызывает «⚠️ ОН ЗДЕСЬ».
* **Случайные события.** `game_prompts` — активный призыв к действию: что
  просили, какие ответы засчитываются (JSONB), до когда и кто выиграл.

Revision ID: 0022_game_journal_prompts
Revises: 0021_game_media_posts
Create Date: 2026-09-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022_game_journal_prompts"
down_revision: str | Sequence[str] | None = "0021_game_media_posts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_journal",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "subject_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("repeat_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_game_journal_pending", "game_journal", ["sent_at", "created_at"]
    )
    op.create_index(
        "ix_game_journal_subject", "game_journal", ["subject_user_id", "kind"]
    )

    op.create_table(
        "game_prompts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "answers",
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
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "winner_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_game_prompts_open", "game_prompts", ["chat_id", "closed_at", "expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_game_prompts_open", table_name="game_prompts")
    op.drop_table("game_prompts")
    op.drop_index("ix_game_journal_subject", table_name="game_journal")
    op.drop_index("ix_game_journal_pending", table_name="game_journal")
    op.drop_table("game_journal")
