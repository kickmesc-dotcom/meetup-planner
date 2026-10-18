"""База стандартов и проверка знаний.

Инструкция (`standards`) + вопросы к ней (`standard_questions`) + результаты
попыток (`standard_checks`). Результат хранится историей: пересдача — нормальная
часть обучения, поэтому в профиле показывается последняя попытка, а предыдущие
остаются для разбора.

Revision ID: 0036_standards
Revises: 0035_task_modes_assignments
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_standards"
down_revision: str | None = "0035_task_modes_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "standards",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("emoji", sa.String(length=16)),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
            server_default="other",
        ),
        sa.Column("summary", sa.Text()),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "department_id",
            sa.BigInteger(),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "pass_percent",
            sa.SmallInteger(),
            nullable=False,
            server_default="80",
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        sa.CheckConstraint(
            "category IN ('dishes', 'equipment', 'safety', 'service', 'other')",
            name="ck_standard_category",
        ),
    )
    op.create_index(
        "ix_standards_active_sort", "standards", ["is_active", "sort_order"]
    )

    op.create_table(
        "standard_questions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "standard_id",
            sa.BigInteger(),
            sa.ForeignKey("standards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "options", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "correct_index", sa.SmallInteger(), nullable=False, server_default="0"
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_standard_questions_standard",
        "standard_questions",
        ["standard_id", "sort_order"],
    )

    op.create_table(
        "standard_checks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "standard_id",
            sa.BigInteger(),
            sa.ForeignKey("standards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("total", sa.SmallInteger(), nullable=False),
        sa.Column("correct", sa.SmallInteger(), nullable=False),
        sa.Column("percent", sa.SmallInteger(), nullable=False),
        sa.Column(
            "passed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("answers", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_standard_checks_employee", "standard_checks", ["employee_id", "at"]
    )
    op.create_index(
        "ix_standard_checks_standard", "standard_checks", ["standard_id", "passed"]
    )


def downgrade() -> None:
    op.drop_index("ix_standard_checks_standard", table_name="standard_checks")
    op.drop_index("ix_standard_checks_employee", table_name="standard_checks")
    op.drop_table("standard_checks")
    op.drop_index("ix_standard_questions_standard", table_name="standard_questions")
    op.drop_table("standard_questions")
    op.drop_index("ix_standards_active_sort", table_name="standards")
    op.drop_table("standards")
