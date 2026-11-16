"""Склад расходников: остаток и движения.

Зачем. Недостача всплывает в конце месяца, когда вспомнить, кто брал
перчатки, уже невозможно. Здесь только то, что нужно для ответа на вопрос
«кто и когда взял»: позиция с остатком и движения с автором. Партий,
поставщиков и цен нет — это чужая область, и полу-учёт в ней только мешает.

Остаток хранится в позиции, а не считается по движениям: экран открывается
на слабом телефоне в подвале, и сумма по всей истории — лишняя работа.
Движения при этом остаются источником правды при разборе спора.

Revision ID: 0077_supplies
Revises: 0076_employee_mentor
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0077_supplies"
down_revision: str | None = "0076_employee_mentor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplies",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False, server_default="шт"),
        sa.Column(
            "quantity", sa.Numeric(10, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "min_quantity", sa.Numeric(10, 2), nullable=False, server_default="0"
        ),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("org_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.CheckConstraint("quantity >= 0", name="ck_supplies_quantity"),
        sa.CheckConstraint("min_quantity >= 0", name="ck_supplies_min"),
    )
    op.create_index("ix_supplies_org_active", "supplies", ["org_id", "is_active"])

    op.create_table(
        "supply_movements",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("supply_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("comment", sa.String(length=300), nullable=True),
        sa.Column("employee_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("org_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["supply_id"], ["supplies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.CheckConstraint("quantity > 0", name="ck_supply_movements_quantity"),
        sa.CheckConstraint("kind IN ('in', 'out')", name="ck_supply_movements_kind"),
    )
    op.create_index(
        "ix_supply_movements_order",
        "supply_movements",
        ["supply_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_supply_movements_order", table_name="supply_movements")
    op.drop_table("supply_movements")
    op.drop_index("ix_supplies_org_active", table_name="supplies")
    op.drop_table("supplies")
