"""Подписки на web push: уведомления без Telegram (шаг 2.4).

Одна строка — одно устройство (endpoint браузера), а не человек: телефон,
компьютер и планшет подписываются независимо и умирают по отдельности.

Ключи `p256dh`/`auth` — не секреты входа: без них нельзя зашифровать
push-сообщение, но нельзя и войти. `endpoint_hash` (SHA-256) — уникальный
ключ вместо длинного URL: btree в Postgres не любит строки в килобайты.
`user_agent` и `last_seen_at` нужны человеку, а не серверу: по ним видно,
какое устройство получает уведомления.

Таблица тенантная (`org_id` NOT NULL) — как все бизнес-таблицы проекта.

Revision ID: 0058_push
Revises: 0057_invitations
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0058_push"
down_revision: str | None = "0057_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("endpoint_hash", sa.String(length=64), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "endpoint_hash", name="uq_push_subscription_endpoint"
        ),
    )
    op.create_index(
        "ix_push_subscriptions_org_user",
        "push_subscriptions",
        ["org_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_push_subscriptions_org_user", table_name="push_subscriptions"
    )
    op.drop_table("push_subscriptions")
