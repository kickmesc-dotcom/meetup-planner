"""Передача смены.

Сдающий фиксирует снимок того, что осталось открытым (поручения и операционные
проблемы), и передаёт карточку конкретному человеку. Принимающий подтверждает
(или возвращает с причиной) — так видно, что чужие хвосты не потерялись между
сменами.

Revision ID: 0034_hr_handovers
Revises: 0033_hr_issue_journal
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0034_hr_handovers"
down_revision: str | None = "0033_hr_issue_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_handovers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "department_id",
            sa.BigInteger(),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "from_employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "to_employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "accepted_by_employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="sent"
        ),
        sa.Column("note", sa.Text()),
        sa.Column("reject_reason", sa.Text()),
        sa.Column("shift_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('sent', 'accepted', 'rejected')",
            name="ck_hr_handover_status",
        ),
    )
    op.create_index(
        "ix_hr_handovers_to", "hr_handovers", ["to_employee_id", "status"]
    )
    op.create_index(
        "ix_hr_handovers_from", "hr_handovers", ["from_employee_id", "created_at"]
    )
    op.create_index("ix_hr_handovers_shift", "hr_handovers", ["shift_date"])

    op.create_table(
        "hr_handover_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "handover_id",
            sa.BigInteger(),
            sa.ForeignKey("hr_handovers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ref_id", sa.BigInteger()),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("meta", sa.String(length=128)),
        sa.CheckConstraint(
            "kind IN ('task', 'issue')", name="ck_hr_handover_item_kind"
        ),
    )
    op.create_index(
        "ix_hr_handover_items_handover", "hr_handover_items", ["handover_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hr_handover_items_handover", table_name="hr_handover_items"
    )
    op.drop_table("hr_handover_items")
    op.drop_index("ix_hr_handovers_shift", table_name="hr_handovers")
    op.drop_index("ix_hr_handovers_from", table_name="hr_handovers")
    op.drop_index("ix_hr_handovers_to", table_name="hr_handovers")
    op.drop_table("hr_handovers")
