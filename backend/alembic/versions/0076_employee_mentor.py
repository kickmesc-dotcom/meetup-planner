"""Наставник новичка: первая неделя с отметками.

Зачем. Новичок уходит на третий день, и узнают об этом в конце месяца, когда
смену уже некому закрыть. Наставник — это конкретный человек, который отвечает
за первые дни, а не «отдел вообще». Пара живёт в той же таблице сотрудников:
наставничество — роль в паре, а не должность, и заводить ради неё отдельную
сущность значило бы держать второй справочник людей.

Почему `SET NULL`. Увольнение наставника не должно ни блокировать увольнение,
ни уносить стажёра. Пара просто распадается, и стажёр снова попадает в список
без наставника — это видно и требует решения.

Revision ID: 0076_employee_mentor
Revises: 0075_org_link_keys
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0076_employee_mentor"
down_revision: str | None = "0075_org_link_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employees", sa.Column("mentor_employee_id", sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        "fk_employees_mentor",
        "employees",
        "employees",
        ["mentor_employee_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_employees_mentor", "employees", ["mentor_employee_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_employees_mentor", table_name="employees")
    op.drop_constraint("fk_employees_mentor", "employees", type_="foreignkey")
    op.drop_column("employees", "mentor_employee_id")
