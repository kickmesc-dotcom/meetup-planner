"""Пересчёт склада и потолок списания на смену.

Зачем пересчёт. Остаток в позиции — это то, что система думает; факт знает
только человек с полкой. Без сверки цифры расходятся молча, и недостача
всплывает в конце месяца. `is_inventory` помечает движение, созданное
сверкой, — по нему строится отчёт по расхождениям.

Зачем потолок. Перчатки можно списывать свободно, бытовую химию — нет.
`max_out_per_shift` ограничивает списание за смену; `NULL` — без ограничения,
поэтому существующие позиции ничего не замечают.

Revision ID: 0079_supply_counts
Revises: 0078_product_events
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0079_supply_counts"
down_revision: str | None = "0078_product_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "supplies", sa.Column("max_out_per_shift", sa.Numeric(10, 2), nullable=True)
    )
    op.add_column(
        "supply_movements",
        sa.Column(
            "is_inventory",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("supply_movements", "is_inventory")
    op.drop_column("supplies", "max_out_per_shift")
