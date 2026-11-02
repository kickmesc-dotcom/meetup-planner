"""Меню смены: позиции, которые руководитель правит в приложении.

Зачем таблица. Меню было единственным документом смены, который правили вне
приложения: снимок листа Google, обновляемый по расписанию. Правка «убрать
рыбу, она кончилась» занимала минуты и требовала второй экран, а до
обновления копии сотрудник видел вчерашнее меню. Теперь строка меню — обычные
данные организации.

Почему цена целыми рублями. В меню нет копеек, а хранение копеек заставляет
каждое место интерфейса помнить про деление на 100 — это лишняя точка ошибки
на ровном месте. Пустая цена означает «по запросу».

Почему `is_available` отдельно от удаления. Перед сменой нужно «сегодня этого
нет», а не «забудьте навсегда»: скрытая позиция хранится целиком и
возвращается одним нажатием.

Таблица тенантная (`org_id` NOT NULL), как все бизнес-таблицы проекта.

Revision ID: 0064_menu_items
Revises: 0063_translation_cache
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0064_menu_items"
down_revision: str | None = "0063_translation_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "menu_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "category",
            sa.String(length=64),
            nullable=False,
            server_default="Меню",
        ),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("price_rub", sa.Integer(), nullable=True),
        sa.Column(
            "is_available", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_by_employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "price_rub IS NULL OR price_rub >= 0", name="ck_menu_items_price"
        ),
    )
    op.create_index("ix_menu_items_org_id", "menu_items", ["org_id"])
    op.create_index(
        "ix_menu_items_order", "menu_items", ["category", "sort_order", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_menu_items_order", table_name="menu_items")
    op.drop_index("ix_menu_items_org_id", table_name="menu_items")
    op.drop_table("menu_items")
