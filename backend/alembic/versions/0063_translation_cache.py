"""Кэш перевода данных (план, 11).

Зачем миграция. Модель перевода (SMaLL-100, int8) живёт только на хосте с
памятью; у Amvera 0,5 ГБ (S-19), и модель там не поднимается. Общая база —
единственный способ отдать уже посчитанный перевод обоим контурам.

Почему `unique(source_hash, target)`, а не просто индекс: два контейнера могут
перевести одну и ту же фразу одновременно, и вставка идёт через
`ON CONFLICT DO NOTHING`. Без ограничения в схеме дубли копились бы молча, а
кэш «одна строка на текст» перестал бы быть кэшем.

Почему нет колонки с исходным текстом: кэш не должен становиться второй копией
заданий. Ключ — sha256(текст + язык), его достаточно для поиска.

Revision ID: 0063_translation_cache
Revises: 0062_kudos
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0063_translation_cache"
down_revision: str | None = "0062_kudos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "translation_cache",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=8), nullable=False),
        sa.Column("translated", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("source_hash", "target", name="uq_translation_hash_target"),
    )


def downgrade() -> None:
    op.drop_table("translation_cache")
