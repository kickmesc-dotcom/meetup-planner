"""Расписание учебных смен и ставка сотрудника.

Новичку нужно понимать, какие смены ещё учебные, а какие уже обычные: раньше
это был один флаг `learning_mode` на весь профиль. Теперь есть план по дням:

* `employees.training_days` — сколько первых смен после `hire_date` учебные;
* `employees.rate_type` — полная или частичная ставка;
* `employee_training_days` — точечные исключения на конкретную дату.

Правило сильнее расчёта, пустая таблица — обычное поведение. Миграция
аддитивная: старые строки получают полную ставку и три учебные смены.

Revision ID: 0043_training_plan
Revises: 0042_task_reminders
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0043_training_plan"
down_revision: str | None = "0042_task_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column(
            "rate_type",
            sa.String(length=16),
            nullable=False,
            server_default="full",
        ),
    )
    op.add_column(
        "employees",
        sa.Column(
            "training_days",
            sa.SmallInteger(),
            nullable=False,
            server_default="3",
        ),
    )
    op.create_check_constraint(
        "ck_employee_rate",
        "employees",
        "rate_type IN ('full', 'partial')",
    )
    op.create_table(
        "employee_training_days",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column(
            "is_training",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "set_by_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("employee_id", "day", name="uq_employee_training_day"),
    )


def downgrade() -> None:
    op.drop_table("employee_training_days")
    op.drop_constraint("ck_employee_rate", "employees", type_="check")
    op.drop_column("employees", "training_days")
    op.drop_column("employees", "rate_type")
