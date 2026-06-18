"""GHG8 T1.2 — weekly_chukhan.reason_text: причина чухана для истории.

Раньше фраза-причина выбиралась на лету при анонсе и нигде не сохранялась —
в сводной истории (профиль) у чухана причины не было (прод-фидбек 15.06 п.1,
п.12). Колонка nullable: старые недели остаются без причины, новые пишут её
при постинге (chukhan.py: row.reason_text).

Revision ID: 0016_chukhan_reason
Revises: 0015_participant_personas
Create Date: 2026-06-18
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_chukhan_reason"
down_revision: str | Sequence[str] | None = "0015_participant_personas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "weekly_chukhan",
        sa.Column("reason_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("weekly_chukhan", "reason_text")
