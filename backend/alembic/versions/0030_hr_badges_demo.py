"""hr: плашка должность/звание и флаг тестового пула `[BOT]`

Плашка (`badge`, `badge_emoji`) — только подпись человека в боте и мини-аппе,
она не влияет на права и не путается с `position` (по должности матчатся
условные пункты чек-листа).

`is_demo` помечает сотрудников-симуляторов: их строки и их активность можно
целиком спрятать или снести одним переключателем (`services/hr_demo.py`), не
задевая боевых людей. Флаг с индексом, потому что по нему фильтруются лента и
списки на каждом запросе.

Revision ID: 0030_hr_badges_demo
Revises: 0029_hr_core
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_hr_badges_demo"
down_revision: str | Sequence[str] | None = "0029_hr_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("badge", sa.Text(), nullable=True))
    op.add_column("employees", sa.Column("badge_emoji", sa.String(length=8), nullable=True))
    op.add_column(
        "employees",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_employees_demo", "employees", ["is_demo"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_employees_demo", table_name="employees")
    op.drop_column("employees", "is_demo")
    op.drop_column("employees", "badge_emoji")
    op.drop_column("employees", "badge")
