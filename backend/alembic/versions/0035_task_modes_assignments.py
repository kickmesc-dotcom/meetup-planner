"""Групповые поручения: режим, смена и личное состояние исполнителя.

Что добавляется:

* `tasks.mode` — `one_of` («один за всех»), `each` («каждый сам»),
  `parts` («части работы»). Существующие поручения получают `one_of`, то есть
  ведут себя ровно как раньше.
* `tasks.shift_date` — на какую смену выдано поручение (`NULL` — без привязки).
* `task_assignments` — строка на каждого исполнителя: статус, часть работы и
  время закрытия. Бэкфилл: по существующим задачам строки не создаём — для них
  работает прежний путь (`tasks.assignee_employee_id` + агрегатный статус),
  а строки появляются, когда поручение правят или создают заново.

Revision ID: 0035_task_modes_assignments
Revises: 0034_hr_handovers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0035_task_modes_assignments"
down_revision: str | None = "0034_hr_handovers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "mode", sa.String(length=16), nullable=False, server_default="one_of"
        ),
    )
    op.add_column("tasks", sa.Column("shift_date", sa.Date()))
    op.create_check_constraint(
        "ck_task_mode", "tasks", "mode IN ('one_of', 'each', 'parts')"
    )
    op.create_index("ix_tasks_shift", "tasks", ["shift_date"])

    op.create_table(
        "task_assignments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="new"
        ),
        sa.Column("part", sa.Text()),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("task_id", "employee_id", name="uq_task_assignment"),
        sa.CheckConstraint(
            "status IN ('new', 'accepted', 'in_progress', 'done', 'overdue', "
            "'failed')",
            name="ck_task_assignment_status",
        ),
    )
    op.create_index(
        "ix_task_assignments_employee", "task_assignments", ["employee_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_task_assignments_employee", table_name="task_assignments")
    op.drop_table("task_assignments")
    op.drop_index("ix_tasks_shift", table_name="tasks")
    op.drop_constraint("ck_task_mode", "tasks", type_="check")
    op.drop_column("tasks", "shift_date")
    op.drop_column("tasks", "mode")
