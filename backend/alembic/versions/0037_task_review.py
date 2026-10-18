"""Проверка руководителем: `on_review` / `rework`.

MEGAPROMT2: у поручения должен быть путь «сдал → приняли» или «вернули на
доработку». Добавляем два статуса и признак `tasks.requires_review`: по
умолчанию выключен, поэтому существующие поручения продолжают закрываться
отметкой исполнителя.

CHECK-констрейнты пересоздаются: набор статусов строковый, а не PG-enum
(см. докстринг `hr_models`), поэтому правка — это drop/create констрейнта.

Revision ID: 0037_task_review
Revises: 0036_standards
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0037_task_review"
down_revision: str | None = "0036_standards"
branch_labels = None
depends_on = None

_OLD = "('new', 'accepted', 'in_progress', 'done', 'overdue', 'failed')"
_NEW = (
    "('new', 'accepted', 'in_progress', 'on_review', 'rework', 'done', "
    "'overdue', 'failed')"
)


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "requires_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.drop_constraint("ck_task_status", "tasks", type_="check")
    op.create_check_constraint("ck_task_status", "tasks", f"status IN {_NEW}")
    op.drop_constraint(
        "ck_task_assignment_status", "task_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_task_assignment_status", "task_assignments", f"status IN {_NEW}"
    )


def downgrade() -> None:
    # Сначала возвращаем «зависшие» статусы в известные, иначе констрейнт не
    # встанет на существующих строках.
    op.execute("UPDATE tasks SET status = 'in_progress' WHERE status IN ('on_review', 'rework')")
    op.execute(
        "UPDATE task_assignments SET status = 'in_progress' "
        "WHERE status IN ('on_review', 'rework')"
    )
    op.drop_constraint(
        "ck_task_assignment_status", "task_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_task_assignment_status", "task_assignments", f"status IN {_OLD}"
    )
    op.drop_constraint("ck_task_status", "tasks", type_="check")
    op.create_check_constraint("ck_task_status", "tasks", f"status IN {_OLD}")
    op.drop_column("tasks", "requires_review")
