"""Ссылки входа в приложение из браузера (веб-версия на ПК).

Внутри Telegram личность подтверждает подписанный `initData`. Прямая ссылка на
Pages открывается в обычном браузере, где `initData` нет, — там нужен свой вход.
Пароль не заводим: сервер выдаёт длинный случайный токен, отдаёт его один раз
в ссылке `?access=…`, а в базе хранит только SHA-256 (утечка дампа не даёт
входа). Срок — 30 дней, ссылку можно отозвать, `last_used_at` показывает
человеку, когда её последний раз использовали.

Revision ID: 0051_app_access_links
Revises: 0050_weekday_schedule_profile
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0051_app_access_links"
down_revision: str | None = "0050_weekday_schedule_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_access_links",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_app_access_links_user", "app_access_links", ["user_id"])
    op.create_index("ix_app_access_links_expires", "app_access_links", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_app_access_links_expires", table_name="app_access_links")
    op.drop_index("ix_app_access_links_user", table_name="app_access_links")
    op.drop_table("app_access_links")
