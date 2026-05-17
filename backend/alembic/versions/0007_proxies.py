"""proxy_entries — пул прокси для AiohttpSession fallback

Revision ID: 0007_proxies
Revises: 0006_birthdays
Create Date: 2026-05-17
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_proxies"
down_revision: str | Sequence[str] | None = "0006_birthdays"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "proxy_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("server", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.String(length=16),
            nullable=False,
            server_default="mtproto",
        ),
        sa.Column("secret", sa.Text(), nullable=True),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "fail_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fail_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("server", "port", name="uq_proxy_server_port"),
    )
    op.create_index(
        "ix_proxy_enabled_dead",
        "proxy_entries",
        ["enabled", "dead_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_proxy_enabled_dead", table_name="proxy_entries")
    op.drop_table("proxy_entries")
