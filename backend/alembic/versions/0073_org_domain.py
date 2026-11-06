"""Свой домен клиента: адрес, который видит его команда.

Зачем. Сейчас у всех организаций один адрес `*.pages.dev`. Для сети это
выглядит как «какой-то бот», а не как приложение салона: сотрудник должен
открывать `cabinet.salon.ru`, а не запоминать платформенную ссылку.

Почему домен один, а не список. У организации один рабочий адрес; несколько
доменов — это уже бренды и регионы, которых пока нет. Одно поле проще
проверять на уникальность и не даёт двум клиентам занять один адрес.

Почему `verified_at` отдельно от самого домена. Домен можно вписать сразу, но
пока владелец не подтвердил контроль (файл на своём домене), включать его
нельзя: иначе чужой человек занял бы домен, который ему не принадлежит, и
сломал бы вход реальному владельцу.

Почему `custom_domain_token`. Проверка — файл по известному адресу с этим
токеном. Токен одноразовый на попытку: смена домена меняет токен, и старая
наклейка на прежнем домене ничего не подтверждает.

Revision ID: 0073_org_domain
Revises: 0072_feed_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0073_org_domain"
down_revision: str | None = "0072_feed_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("custom_domain", sa.String(253)))
    op.add_column("organizations", sa.Column("custom_domain_token", sa.String(64)))
    op.add_column(
        "organizations",
        sa.Column("custom_domain_verified_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "organizations",
        sa.Column("custom_domain_checked_at", sa.DateTime(timezone=True)),
    )
    # NULL'ы в PG уникальности не мешают: организация без своего домена
    # встречается сколько угодно раз, а занятый адрес — только один.
    op.create_index(
        "uq_organizations_custom_domain",
        "organizations",
        ["custom_domain"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_organizations_custom_domain", table_name="organizations")
    op.drop_column("organizations", "custom_domain_checked_at")
    op.drop_column("organizations", "custom_domain_verified_at")
    op.drop_column("organizations", "custom_domain_token")
    op.drop_column("organizations", "custom_domain")
