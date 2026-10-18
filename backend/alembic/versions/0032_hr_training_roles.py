"""Обучение в онбординге и ручная фиксация роли.

Две вещи одного шага:

* `employees.role_locked` — признак «роль меняли руками». Без него
  `hr_access.ensure_employee` возвращал бы env-админу `admin` на следующем
  запросе, и сценарий «снять себе роль, посмотреть как работают задачи»
  ломался бы сразу после первого экрана.
* таблица `employee_training_steps` + новое состояние онбординга `training`:
  знакомство с приложением стало этапом (уроки «где чек-лист», «как отправить
  фотоотчёт» и т.п.), а не только выбором подразделения и опыта.

Revision ID: 0032_hr_training_roles
Revises: 0031_hr_achievements
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0032_hr_training_roles"
down_revision: str | None = "0031_hr_achievements"
branch_labels = None
depends_on = None

_STATES = "('new', 'department', 'experience', 'training', 'done')"
_STATES_OLD = "('new', 'department', 'experience', 'done')"


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column(
            "role_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.drop_constraint("ck_employee_onboarding_state", "employees", type_="check")
    op.create_check_constraint(
        "ck_employee_onboarding_state",
        "employees",
        f"onboarding_state IN {_STATES}",
    )

    op.create_table(
        "employee_training_steps",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "employee_id", "code", name="uq_employee_training_step_code"
        ),
    )
    op.create_index(
        "ix_employee_training_steps_employee",
        "employee_training_steps",
        ["employee_id", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_training_steps_employee", table_name="employee_training_steps"
    )
    op.drop_table("employee_training_steps")
    op.drop_constraint("ck_employee_onboarding_state", "employees", type_="check")
    op.create_check_constraint(
        "ck_employee_onboarding_state",
        "employees",
        f"onboarding_state IN {_STATES_OLD}",
    )
    op.drop_column("employees", "role_locked")
