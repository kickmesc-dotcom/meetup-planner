"""Журнал операционных проблем как отдельная сущность.

Проблема смены больше не обязана жить внутри поручения: карточка с категорией,
зоной, срочностью и ответственным заводится сама, ходит между сменами и хранит
историю (`hr_issue_events`), поэтому через неделю видно, кто её создал, кому
передавали и когда закрыли.

`task_id` — необязательная ссылка: если проблема пришла из поручения, карточка
остаётся связанной с ним, но не удаляется вместе с задачей (`SET NULL`).

Revision ID: 0033_hr_issue_journal
Revises: 0032_hr_training_roles
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0033_hr_issue_journal"
down_revision: str | None = "0032_hr_training_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_issues",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
            server_default="other",
        ),
        sa.Column("zone", sa.String(length=64)),
        sa.Column(
            "severity",
            sa.String(length=16),
            nullable=False,
            server_default="normal",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "department_id",
            sa.BigInteger(),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "assignee_employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_by_employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
        ),
        sa.Column("shift_date", sa.Date(), nullable=False),
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
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "category IN ('equipment', 'supplies', 'staffing', 'guest', "
            "'cleanliness', 'safety', 'it', 'other')",
            name="ck_hr_issue_category",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'normal', 'high', 'critical')",
            name="ck_hr_issue_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'cancelled')",
            name="ck_hr_issue_status",
        ),
    )
    op.create_index(
        "ix_hr_issues_status", "hr_issues", ["status", "severity"]
    )
    op.create_index(
        "ix_hr_issues_department", "hr_issues", ["department_id", "status"]
    )
    op.create_index(
        "ix_hr_issues_assignee", "hr_issues", ["assignee_employee_id", "status"]
    )
    op.create_index("ix_hr_issues_shift", "hr_issues", ["shift_date"])

    op.create_table(
        "hr_issue_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "issue_id",
            sa.BigInteger(),
            sa.ForeignKey("hr_issues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("from_status", sa.String(length=16)),
        sa.Column("to_status", sa.String(length=16)),
        sa.Column(
            "by_employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
        ),
        sa.Column("comment", sa.Text()),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_hr_issue_events_issue", "hr_issue_events", ["issue_id", "at"]
    )


def downgrade() -> None:
    op.drop_index("ix_hr_issue_events_issue", table_name="hr_issue_events")
    op.drop_table("hr_issue_events")
    op.drop_index("ix_hr_issues_shift", table_name="hr_issues")
    op.drop_index("ix_hr_issues_assignee", table_name="hr_issues")
    op.drop_index("ix_hr_issues_department", table_name="hr_issues")
    op.drop_index("ix_hr_issues_status", table_name="hr_issues")
    op.drop_table("hr_issues")
