"""Бренд организации: своё имя, цвет и логотип (B2B_PLATFORM_PLAN, 4.4).

Зачем колонки, а не отдельная таблица. Бренд читается на каждом старте
приложения (имя в заголовке, цвет ссылок), а полей три. Таблица дала бы join
на старте ради трёх строк.

Почему `brand_name` может быть пустым. Пусто — «бренд не настроен», и клиент
видит имя организации (`organizations.name`), а не бренд платформы: у новой
организации ничего настраивать ещё не успели, и подставлять чужое имя нельзя.

Почему `brand_color` — строка, а не число. Это CSS-цвет (`#1c6fb8`), его
сравнивают и логируют как текст; хранение числом потребовало бы обратного
преобразования на каждом чтении.

Почему логотип — URL, а не файл. Загрузка файла требует хранилища и чистки
сирот; на этом шаге клиент размещает логотип на своём CDN, а мы проверяем
только `https`-адрес. Когда появится загрузка, поле останется тем же.

Revision ID: 0067_org_brand
Revises: 0066_org_billing
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0067_org_brand"
down_revision: str | None = "0066_org_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("brand_name", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("brand_color", sa.String(length=9), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("brand_logo_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "brand_logo_url")
    op.drop_column("organizations", "brand_color")
    op.drop_column("organizations", "brand_name")
