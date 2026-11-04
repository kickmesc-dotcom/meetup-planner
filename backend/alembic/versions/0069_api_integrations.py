"""Публичный API и вебхуки с ключами по организации (B2B_PLATFORM_PLAN, 6.1).

Зачем ключ, а не пароль владельца. Интегратору (CRM, телефония, учётная
система) нужен доступ к людям и графику, но не к кабинету: пароль дал бы ему
всё, включая удаление организации. Ключ — отдельная сущность со своим сроком
жизни, набором прав и отзывом в один клик.

Почему в базе только хеш. Ключ показывается один раз при создании; в базе
лежит SHA-256 и префикс. Утечка дампа не даёт чужим доступ к API — тот же
принцип, что у приглашений и сессий.

Почему `webhook_deliveries` отдельной таблицей, а не полем в endpoint. Доставка
может не пройти с первого раза (интегратор лежит), и вопрос «что мы ему
отправили и чем это кончилось» должен иметь ответ через сутки. Журнал
обрезается по сроку, чтобы не превратиться в архив.

Revision ID: 0069_api_integrations
Revises: 0068_org_privacy
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0069_api_integrations"
down_revision: str | None = "0068_org_privacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        # Первые символы ключа — чтобы человек узнал его в списке, не видя
        # самого ключа: «stk_live_7fa2…».
        sa.Column("prefix", sa.String(length=24), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.String(length=240), nullable=False, server_default=""),
        sa.Column(
            "created_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_org_id", "api_keys", ["org_id"])
    op.create_index("ix_api_keys_token_hash", "api_keys", ["token_hash"], unique=True)

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        # Секрет подписи: интегратор проверяет, что запрос от нас, а не от
        # того, кто узнал его URL.
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column("events", sa.String(length=300), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        # Подряд идущие неудачи: по ним endpoint помечается проблемным, но
        # не выключается сам — интегратор чинит приёмник, а не догадывается,
        # почему вебхуки перестали приходить.
        sa.Column(
            "failures", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.create_index("ix_webhook_endpoints_org_id", "webhook_endpoints", ["org_id"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "endpoint_id",
            sa.BigInteger(),
            sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(length=48), nullable=False),
        # Тело хранится снимком: повтор должен отправлять то же, что и первый
        # раз, даже если данные уже поменялись.
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_webhook_deliveries_org_time",
        "webhook_deliveries",
        ["org_id", "created_at"],
    )
    op.create_index(
        "ix_webhook_deliveries_due",
        "webhook_deliveries",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_due", table_name="webhook_deliveries")
    op.drop_index(
        "ix_webhook_deliveries_org_time", table_name="webhook_deliveries"
    )
    op.drop_table("webhook_deliveries")
    op.drop_index("ix_webhook_endpoints_org_id", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")
    op.drop_index("ix_api_keys_token_hash", table_name="api_keys")
    op.drop_index("ix_api_keys_org_id", table_name="api_keys")
    op.drop_table("api_keys")
