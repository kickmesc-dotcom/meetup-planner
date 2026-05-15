"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-08

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("username", sa.Text()),
        sa.Column("avatar_url", sa.Text()),
        sa.Column("color_hex", sa.String(length=7), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="Europe/Moscow"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "availability_ranges",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("confidence", sa.SmallInteger(), nullable=False, server_default="3"),
        sa.Column("note", sa.Text()),
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
        sa.CheckConstraint("confidence BETWEEN 1 AND 5", name="ck_avail_confidence"),
    )
    op.create_index(
        "ix_avail_user_time",
        "availability_ranges",
        ["user_id", "starts_at", "ends_at"],
    )

    op.create_table(
        "meetings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="proposed"),
        sa.Column(
            "auto_picked", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("score", sa.Numeric(5, 2)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "meeting_attendance",
        sa.Column(
            "meeting_id",
            sa.BigInteger(),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("rsvp", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("showed_up", sa.Boolean()),
    )

    op.create_table(
        "polls",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True)),
        sa.Column("tg_message_id", sa.BigInteger()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "poll_options",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "poll_id",
            sa.BigInteger(),
            sa.ForeignKey("polls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.Text()),
    )

    op.create_table(
        "poll_votes",
        sa.Column(
            "poll_option_id",
            sa.BigInteger(),
            sa.ForeignKey("poll_options.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "voted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "loser_rolls",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "rolled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "rolled_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "loser_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("reason_text", sa.Text()),
    )
    op.create_index("ix_loser_rolled_at", "loser_rolls", ["rolled_at"])

    op.create_table(
        "event_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # GIST index requires btree_gist on Postgres for tstzrange -- safe to no-op
    # if dialect doesn't support it (sqlite tests).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        op.execute(
            "CREATE INDEX ix_avail_time ON availability_ranges "
            "USING gist (tstzrange(starts_at, ends_at, '[)'))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_avail_time")

    op.drop_table("event_log")
    op.drop_index("ix_loser_rolled_at", table_name="loser_rolls")
    op.drop_table("loser_rolls")
    op.drop_table("poll_votes")
    op.drop_table("poll_options")
    op.drop_table("polls")
    op.drop_table("meeting_attendance")
    op.drop_table("meetings")
    op.drop_index("ix_avail_user_time", table_name="availability_ranges")
    op.drop_table("availability_ranges")
    op.drop_table("users")
