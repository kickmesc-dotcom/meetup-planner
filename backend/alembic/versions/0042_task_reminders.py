"""Ручная правка напоминаний: «передвинуть» и «выключить» из админки.

Напоминания о сроке не хранятся отдельными строками: планировщик считает их из
`tasks.due_at` и настройки «за сколько минут». Чтобы управляющий мог сдвинуть
или выключить напоминание по конкретному поручению, не меняя срок, заводим
одну строку-правило на задачу:

* `remind_at` — своё время отправки (сильнее расчёта);
* `skip` — не напоминать вовсе, пока правило не уберут.

Удаление строки возвращает поведение по умолчанию.

Revision ID: 0042_task_reminders
Revises: 0041_employee_lifecycle
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0042_task_reminders"
down_revision: str | None = "0041_employee_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_reminders",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "skip",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "updated_by_id",
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
        sa.UniqueConstraint("task_id", name="uq_task_reminders_task"),
    )


def downgrade() -> None:
    op.drop_table("task_reminders")
