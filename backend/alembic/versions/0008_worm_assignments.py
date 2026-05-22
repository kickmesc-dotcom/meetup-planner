"""worm_assignments — особая номинация «Червь-пидор» (E8, GHG6)

Революция: при ролле лоха с шансом `admin_config["worm.chance"]` (default 0.01)
выбранный участник получает дополнительный статус «червь-пидор». Звание
переходящее: в любой момент существует не более одного активного червя
(partial unique index на user_id WHERE ended_at IS NULL).

Revision ID: 0008_worm_assignments
Revises: 0007_proxies
Create Date: 2026-05-21
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_worm_assignments"
down_revision: str | Sequence[str] | None = "0007_proxies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worm_assignments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_loser_roll_id",
            sa.BigInteger(),
            sa.ForeignKey("loser_rolls.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Активный червь — не более одного: ровно одна строка с ended_at IS NULL.
    # На Postgres partial unique работает, но это уникальность по «нулевому
    # значению user_id» нам не нужна — мы запрещаем именно «двух живых»
    # независимо от того, кто это. Поэтому индекс по константе с фильтром.
    op.execute(
        "CREATE UNIQUE INDEX uq_worm_active_singleton "
        "ON worm_assignments ((1)) WHERE ended_at IS NULL"
    )
    op.create_index(
        "ix_worm_user_started",
        "worm_assignments",
        ["user_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_worm_user_started", table_name="worm_assignments")
    op.execute("DROP INDEX IF EXISTS uq_worm_active_singleton")
    op.drop_table("worm_assignments")
