"""Режим проверки: теневые профили и сеансы имитации.

MEGAPROMT3: управляющему нужно пройти приложение глазами сотрудника, не
загрязняя реальную историю. Для этого у каждого сеанса свой теневой профиль
(`employees.is_simulation`), а все тестовые задачи, смены и проблемы висят на
нём. Сеанс (`hr_simulation_sessions`) хранит аудит: кто, кого и в каком режиме
проверял, и сколько тестовых записей удалено при выходе.

Revision ID: 0039_simulation
Revises: 0038_standard_required
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0039_simulation"
down_revision: str | None = "0038_standard_required"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column(
            "is_simulation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_employees_simulation", "employees", ["is_simulation"], unique=False
    )

    op.create_table(
        "hr_simulation_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor_employee_id", sa.BigInteger(), nullable=True),
        sa.Column("subject_employee_id", sa.BigInteger(), nullable=True),
        sa.Column("shadow_employee_id", sa.BigInteger(), nullable=True),
        sa.Column("subject_name", sa.Text(), nullable=True),
        sa.Column("subject_department_name", sa.Text(), nullable=True),
        sa.Column(
            "mode", sa.String(length=16), server_default="new", nullable=False
        ),
        sa.Column(
            "status", sa.String(length=16), server_default="active", nullable=False
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleanup_error", sa.Text(), nullable=True),
        sa.Column("tasks_cleaned", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("runs_cleaned", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("issues_cleaned", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'ended', 'failed')", name="ck_sim_status"
        ),
        sa.CheckConstraint("mode IN ('new', 'as_is')", name="ck_sim_mode"),
        sa.ForeignKeyConstraint(
            ["actor_employee_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["shadow_employee_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["subject_employee_id"], ["employees.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sim_sessions_actor",
        "hr_simulation_sessions",
        ["actor_employee_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sim_sessions_actor", table_name="hr_simulation_sessions")
    op.drop_table("hr_simulation_sessions")
    op.drop_index("ix_employees_simulation", table_name="employees")
    op.drop_column("employees", "is_simulation")
