"""Табель смен: одна строка на сотрудника и день.

Зачем: «первые N смен» считались календарными днями от даты найма, поэтому
больничный или пропуск молча съедали учебную смену. Теперь есть фактический
табель (`worked` / `sick` / `absent` / `dayoff` / `vacation` / `planned`), и
учебные смены считаются по отработанным.

`moved_from` хранит исходную дату при переносе смены, чтобы в табеле была
видна история, а не просто «смена исчезла со вчера и появилась сегодня».

Revision ID: 0044_shifts
Revises: 0043_training_plan
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0044_shifts"
down_revision: str | None = "0043_training_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_shifts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="planned",
        ),
        sa.Column("starts_at", sa.Time(), nullable=True),
        sa.Column("ends_at", sa.Time(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("moved_from", sa.Date(), nullable=True),
        sa.Column(
            "created_by_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("employee_id", "day", name="uq_hr_shift_day"),
        sa.CheckConstraint(
            "status IN ('planned', 'worked', 'sick', 'absent', 'dayoff', 'vacation')",
            name="ck_hr_shift_status",
        ),
    )
    op.create_index("ix_hr_shifts_day", "hr_shifts", ["day"])


def downgrade() -> None:
    op.drop_index("ix_hr_shifts_day", table_name="hr_shifts")
    op.drop_table("hr_shifts")
