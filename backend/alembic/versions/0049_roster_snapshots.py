"""Снапшоты состава: страховка для пула Telegram-ID.

Зачем. Любое удаление людей (`fire` с режимом `purge`, `demo/purge` с
`delete_employees`) необратимо: Telegram-ID не восстановить из Telegram, их
придётся заново собирать у сотрудников. Поэтому перед таким действием сервис
складывает состав в `hr_roster_snapshots`, а из админки его можно вернуть одной
кнопкой.

`payload` — JSONB-список людей без внутренних `id` (восстановление идёт по
`telegram_id`). `kind` различает ручные снимки и автоматические (перед
удалением); `source` говорит, какое действие их сняло.

Revision ID: 0049_roster_snapshots
Revises: 0048_shift_templates
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0049_roster_snapshots"
down_revision: str | None = "0048_shift_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_roster_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("source", sa.String(48), nullable=False, server_default=""),
        sa.Column("people_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_by_employee_id",
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
        sa.CheckConstraint(
            "kind IN ('manual', 'auto')", name="ck_roster_snapshot_kind"
        ),
    )
    op.create_index(
        "ix_roster_snapshots_created", "hr_roster_snapshots", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_roster_snapshots_created", table_name="hr_roster_snapshots")
    op.drop_table("hr_roster_snapshots")
