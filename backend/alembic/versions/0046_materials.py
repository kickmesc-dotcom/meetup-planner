"""Материалы смены: график, меню и бар из Google Sheets.

Ссылки взял владелец (`use_links.md`), но открывать их из России нестабильно.
Теперь сервер раз в N минут забирает CSV и хранит последний удачный снимок;
приложение показывает его из своей БД.

Revision ID: 0046_materials
Revises: 0045_media
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0046_materials"
down_revision: str | None = "0045_media"
branch_labels = None
depends_on = None

# (title, emoji, spreadsheet_id, gid, sort_order)
SEED = (
    (
        "График смен",
        "🗓",
        "1ELeiAoEd5Dm6piTIXmFXjmgBEyOWORSLWi_mjH1pmag",
        "1840299687",
        10,
    ),
    (
        "Меню",
        "🍽",
        "1IksAUaNYIq0vSDGeZ9EuDeh7JNGPURT-kYX85UzuKSs",
        "867527689",
        20,
    ),
    (
        "Бар · методичка",
        "🍸",
        "1NkAXYXjgyKh_hrZaf8KMoKYL51724IGwj_8EeuVBGEM",
        "994124528",
        30,
    ),
)


def upgrade() -> None:
    op.create_table(
        "sheet_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("spreadsheet_id", sa.String(length=128), nullable=False),
        sa.Column("gid", sa.String(length=32), nullable=True),
        sa.Column(
            "department_id",
            sa.BigInteger(),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("rows_json", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "spreadsheet_id", "gid", name="uq_sheet_sources_sheet"
        ),
    )
    op.create_index("ix_sheet_sources_sort", "sheet_sources", ["sort_order", "id"])

    sheet_sources = sa.table(
        "sheet_sources",
        sa.column("title", sa.Text()),
        sa.column("emoji", sa.String()),
        sa.column("url", sa.Text()),
        sa.column("spreadsheet_id", sa.String()),
        sa.column("gid", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        sheet_sources,
        [
            {
                "title": title,
                "emoji": emoji,
                "url": (
                    f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
                    f"?gid={gid}"
                ),
                "spreadsheet_id": sheet_id,
                "gid": gid,
                "sort_order": order,
                "is_active": True,
                "created_at": datetime(2026, 10, 20),
            }
            for title, emoji, sheet_id, gid, order in SEED
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_sheet_sources_sort", table_name="sheet_sources")
    op.drop_table("sheet_sources")
