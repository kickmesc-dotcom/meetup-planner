"""Счётчики использования фич.

Зачем. Ошибки уже ловятся телеметрией, а вопрос «этим вообще пользуются?» —
нет. Без ответа нельзя ни оценить десять сделанных фич, ни решить, что
развивать. Здесь только пара «фича + действие» и тип устройства: ни имени
сотрудника, ни текста, ни адреса.

`org_id` — обязательный: сводка показывается руководителю и не должна
смешивать организации.

Revision ID: 0078_product_events
Revises: 0077_supplies
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0078_product_events"
down_revision: str | None = "0077_supplies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("feature", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("screen", sa.String(length=64), nullable=True),
        sa.Column("device", sa.String(length=32), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("org_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_product_events_lookup",
        "product_events",
        ["org_id", "created_at", "feature"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_events_lookup", table_name="product_events")
    op.drop_table("product_events")
