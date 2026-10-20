"""Шаблоны недели табеля по подразделению.

До этой миграции шаблон жил только в форме листа «Шаблон недели»: собрал
подборку — применил — она исчезла. Управляющий просил сохранять типовую неделю
официанта или бармена и выдавать её новому сотруднику в один тап. Шаблон хранит
рисунок недели (день недели + статус + часы), а не даты, поэтому не устаревает.

Revision ID: 0048_shift_templates
Revises: 0047_checklist_halls
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0048_shift_templates"
down_revision: str | None = "0047_checklist_halls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_shift_templates",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "department_id",
            sa.BigInteger(),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "pattern",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
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
        sa.UniqueConstraint(
            "department_id", "name", name="uq_hr_shift_template_name"
        ),
    )
    op.create_index(
        "ix_hr_shift_templates_department",
        "hr_shift_templates",
        ["department_id", "name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hr_shift_templates_department", table_name="hr_shift_templates"
    )
    op.drop_table("hr_shift_templates")
