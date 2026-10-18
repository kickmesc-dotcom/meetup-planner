"""Обязательные стандарты: `standards.is_required`.

MEGAPROMT2: отчёт смены должен отвечать не только «кто не закрыл чек-лист»,
но и «кто не знает обязательную инструкцию». Для этого стандарту нужен признак
обязательности: необязательные остаются справочником, обязательные попадают в
пробелы отчёта по подразделению.

По умолчанию `false`: уже заведённые стандарты не должны внезапно стать
обязательными для всех отделов.

Revision ID: 0038_standard_required
Revises: 0037_task_review
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0038_standard_required"
down_revision: str | None = "0037_task_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "standards",
        sa.Column(
            "is_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Пробелы считаются по активным обязательным стандартам — частичный индекс
    # ровно под этот запрос.
    op.create_index(
        "ix_standards_required",
        "standards",
        ["is_required", "is_active"],
        postgresql_where=sa.text("is_required"),
    )


def downgrade() -> None:
    op.drop_index("ix_standards_required", table_name="standards")
    op.drop_column("standards", "is_required")
