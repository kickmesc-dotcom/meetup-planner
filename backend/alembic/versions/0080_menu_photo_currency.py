"""Фото блюда и валюта цен организации.

Зачем фото. Меню читает официант в зале, а не повар на кухне: «Рыба дня» без
картинки не отвечает на вопрос гостя «а как это выглядит». Снимок уже умеет
принимать и сжимать `hr_media`, поэтому в `menu_items` лежит только ссылка на
блоб (`photo_blob_id`), а не байты: две копии одного снимка разошлись бы при
первой же правке.

Зачем валюта. «320 ₽» — это не свойство позиции, а свойство организации:
у салона в Алматы цены в тенге, и подставлять рубль в каждой строке меню
значит показывать гостю неверную цену. Поле живёт в `organizations`, поэтому
одна валют на всю организацию, а не «у каждой позиции своя».

`server_default` у валюты обязателен: у существующих организаций колонка
должна получить значение без ручной правки, иначе NOT NULL упадёт на живой
базе.

Revision ID: 0080_menu_photo_currency
Revises: 0079_supply_counts
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0080_menu_photo_currency"
down_revision: str | None = "0079_supply_counts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "menu_items",
        sa.Column("photo_blob_id", sa.BigInteger(), nullable=True),
    )
    # `SET NULL`, а не `CASCADE`: удаление снимка не должно уносить позицию
    # меню вместе с ценой и описанием. Фото — украшение строки, не её смысл.
    op.create_foreign_key(
        "fk_menu_items_photo_blob",
        "menu_items",
        "media_blobs",
        ["photo_blob_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "organizations",
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="RUB"
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "currency")
    op.drop_constraint("fk_menu_items_photo_blob", "menu_items", type_="foreignkey")
    op.drop_column("menu_items", "photo_blob_id")
