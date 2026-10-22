"""Свой бот, секрет вебхука и чат у организации (шаг 1.6).

Последний шаг фазы 1 B2B_PLATFORM_PLAN: до него `BOT_TOKEN` и
`GROUP_CHAT_ID` были в env, то есть один бот обслуживал одного клиента.

Что делает:

1. добавляет `bot_token`, `bot_username`, `webhook_secret`, `group_chat_id`
   в `organizations` — все NULLABLE: пустое значение означает «как раньше»,
   бот и чат берутся из env. Поэтому текущий контур после миграции ведёт себя
   ровно так же, а новый клиент получает свою строку;
2. ставит уникальные индексы на `bot_token` и `webhook_secret`. NULL'ы в PG
   уникальности не мешают, а вот два одинаковых секрета означали бы, что
   входящий апдейт нельзя однозначно отнести к организации.

Секреты в миграции не заполняются: env-значения не должны попадать в историю
базы, их подставляет сервис `app/services/org_bots.py`.

Revision ID: 0055_org_bot
Revises: 0054_tenant_columns
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0055_org_bot"
down_revision: str | None = "0054_tenant_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("bot_token", sa.Text(), nullable=True))
    op.add_column(
        "organizations", sa.Column("bot_username", sa.String(length=64), nullable=True)
    )
    op.add_column("organizations", sa.Column("webhook_secret", sa.Text(), nullable=True))
    op.add_column(
        "organizations", sa.Column("group_chat_id", sa.BigInteger(), nullable=True)
    )
    op.create_index(
        "uq_organization_bot_token", "organizations", ["bot_token"], unique=True
    )
    op.create_index(
        "uq_organization_webhook_secret",
        "organizations",
        ["webhook_secret"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_organization_webhook_secret", table_name="organizations")
    op.drop_index("uq_organization_bot_token", table_name="organizations")
    op.drop_column("organizations", "group_chat_id")
    op.drop_column("organizations", "webhook_secret")
    op.drop_column("organizations", "bot_username")
    op.drop_column("organizations", "bot_token")
