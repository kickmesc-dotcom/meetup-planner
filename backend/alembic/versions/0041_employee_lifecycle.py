"""Увольнение сотрудника: корзина на 30 дней или удаление сразу.

MEGAPROMT3: у управляющего должна быть кнопка «уволить сотрудника» с двойным
подтверждением. Она закрывает доступ в мини-апп и к боту, а с данными человек
выбирает сам:

* `trash` — данные остаются 30 дней и восстанавливаются одним нажатием;
* `purge` — данные удаляются сразу и бесповоротно.

Флаги живут на самом профиле: `fired_at` (когда уволили), `purge_after`
(когда корзина истечёт — по этому полю работает планировщик) и `fired_mode`
(что именно выбрали).

Revision ID: 0041_employee_lifecycle
Revises: 0040_learning_mode
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0041_employee_lifecycle"
down_revision: str | None = "0040_learning_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column("fired_mode", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_employees_purge_after",
        "employees",
        ["purge_after"],
    )


def downgrade() -> None:
    op.drop_index("ix_employees_purge_after", table_name="employees")
    op.drop_column("employees", "fired_mode")
    op.drop_column("employees", "purge_after")
    op.drop_column("employees", "fired_at")
