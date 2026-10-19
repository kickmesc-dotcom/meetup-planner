"""«Учимся вместе»: режим продолжения обучения.

MEGAPROMT3, п. 4.4: после первого сценария сотрудник выбирает, продолжаем ли
мы обучение в следующих сменах или переходим в обычный рабочий режим. Флаг
живёт на профиле и ничего не блокирует: обязательные чек-листы, поручения и
уведомления работают одинаково в обоих режимах — отключается только обучающее
сопровождение, а не обязанности.

Revision ID: 0040_learning_mode
Revises: 0039_simulation
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0040_learning_mode"
down_revision: str | None = "0039_simulation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column(
            "learning_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("employees", "learning_mode")
