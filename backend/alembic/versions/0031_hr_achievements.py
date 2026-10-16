"""hr: скрытые ачивки сотрудника (личный прогресс)

Отдельная таблица, а не колонки в `employees`: ачивки копятся строками
(код + дата выдачи), поэтому выдать их можно ровно один раз и показать историей,
а каталог порогов живёт в коде (`services/hr_achievements.py`) и правится без
миграции.

`unique(employee_id, code)` — идемпотентность пересчёта, который идёт НА ЧТЕНИЕ
профиля: повторный расчёт не дублирует строку. Индекс по
`(employee_id, awarded_at)` — под выборку «мои ачивки по порядку выдачи».

Revision ID: 0031_hr_achievements
Revises: 0030_hr_badges_demo
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031_hr_achievements"
down_revision: str | Sequence[str] | None = "0030_hr_badges_demo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employee_achievements",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column(
            "awarded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "employee_id", "code", name="uq_employee_achievement_code"
        ),
    )
    op.create_index(
        "ix_employee_achievements_employee",
        "employee_achievements",
        ["employee_id", "awarded_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_achievements_employee", table_name="employee_achievements"
    )
    op.drop_table("employee_achievements")
