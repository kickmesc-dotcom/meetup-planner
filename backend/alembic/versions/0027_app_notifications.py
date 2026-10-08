"""GHG11(9) — личные уведомления внутри мини-аппа.

Первая причина их существования: лайк чужого трека. В общий чат такое не пишем
(шестёрке это не новость), а автору трека надо узнать — поэтому отдельная
таблица `app_notifications` и колокольчик с бейджем непрочитанных в приложении.

`payload` — JSONB: `track_id` и что угодно ещё для новых типов уведомлений, без
новых колонок и миграций. Обе выборки (лента уведомлений и счётчик непрочитанных)
идут по своим индексам; `ON DELETE CASCADE` — без пользователя уведомление
смысла не имеет.

Revision ID: 0027_app_notifications
Revises: 0026_music_track_likes
Create Date: 2026-10-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0027_app_notifications"
down_revision: str | Sequence[str] | None = "0026_music_track_likes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_app_notifications_user", "app_notifications", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_app_notifications_unread", "app_notifications", ["user_id", "read_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_app_notifications_unread", table_name="app_notifications")
    op.drop_index("ix_app_notifications_user", table_name="app_notifications")
    op.drop_table("app_notifications")
