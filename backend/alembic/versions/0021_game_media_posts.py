"""GHG10 Э7 — телеметрия мем-постов (мемолог / успешный успех / опиум).

Задание требует четыре ачивки, которые нельзя посчитать по уже существующим
таблицам: «мемолог» (отреагировали все живые), «forever alone» (12 часов
тишины), «опиум для никого» (три поста без реакций) и «успешный успех» (десять
постов с реакциями). Всё это — про конкретный пост: кто его скинул, кто успел
отреагировать в течение часа и чем дело кончилось через 12 часов.

`chat_messages` для этого не годится: там только текст (медиа не сохраняется),
а `media_reactions` держит реакции в памяти процесса и теряет их при рестарте
Space. Поэтому отдельная таблица.

* `responders` / `window_responders` — JSONB-списки user_id: отклики вообще и
  отклики, успевшие в окно реакции (`MEME_REACTION_WINDOW_MIN`).
* `memelog_done` — вердикт по «Мемологу» вынесен (окно закрылось).
* `outcome`/`resolved_at` — итог 12-часового рубежа: `alive` или `dead`.

Unique (chat_id, tg_message_id) — телеграм может доставить апдейт дважды, а
двойной учёт поста сломал бы счётчики.

Revision ID: 0021_game_media_posts
Revises: 0020_game_levelup
Create Date: 2026-09-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_game_media_posts"
down_revision: str | Sequence[str] | None = "0020_game_levelup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_media_posts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "responders",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "window_responders",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "memelog_done",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "chat_id", "tg_message_id", name="uq_game_media_post_msg"
        ),
    )
    op.create_index(
        "ix_game_media_chat_posted",
        "game_media_posts",
        ["chat_id", "posted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_game_media_chat_posted", table_name="game_media_posts")
    op.drop_table("game_media_posts")
