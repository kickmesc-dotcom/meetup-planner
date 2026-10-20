"""Фото внутри приложения: байты в `media_blobs`, а не только TG file_id.

Зачем: мини-апп не мог показать фотоотчёт (у `<img>` нет доступа к Bot API), а
если Telegram недоступен — фото не открывалось вовсе. Теперь снимок можно снять
или выбрать прямо в приложении, байты лежат в БД и отдаются по подписанной
ссылке. `file_id` остаётся для фото из чата (кеш заполняет `media_id`).

Revision ID: 0045_media
Revises: 0044_shifts
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0045_media"
down_revision: str | None = "0044_shifts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_blobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime", sa.String(length=64), nullable=False, server_default="image/jpeg"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("telegram_file_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("sha256", name="uq_media_blobs_sha"),
    )
    op.create_index("ix_media_blobs_created", "media_blobs", ["created_at"])

    op.add_column(
        "task_photos", sa.Column("media_id", sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        "fk_task_photos_media",
        "task_photos",
        "media_blobs",
        ["media_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("task_photos", "file_id", existing_type=sa.Text(), nullable=True)

    op.add_column(
        "checklist_completions",
        sa.Column("photo_media_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_checklist_completions_media",
        "checklist_completions",
        "media_blobs",
        ["photo_media_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_checklist_completions_media", "checklist_completions", type_="foreignkey"
    )
    op.drop_column("checklist_completions", "photo_media_id")
    op.drop_constraint("fk_task_photos_media", "task_photos", type_="foreignkey")
    op.drop_column("task_photos", "media_id")
    op.alter_column("task_photos", "file_id", existing_type=sa.Text(), nullable=False)
    op.drop_index("ix_media_blobs_created", table_name="media_blobs")
    op.drop_table("media_blobs")
