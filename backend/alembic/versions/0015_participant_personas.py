"""GHG8 P6.1 — participant_personas: типажи участников для генератора фраз v2.

Тексты персоналий НЕ хранятся в git (проект публикуется открытым репо,
GHG7.txt стр. 160) — только в Neon. Сидинг — руками пользователя через
админку (P6.1.b), не миграцией.

Формат persona_text — см. app/services/personas.py (секции [слоты]/[шаблоны]).
Одна строка на участника (PK = user_id) — нагрузка на Neon нулевая: SELECT
всех персоналий только в момент генерации фразы (раз в N часов) и в админке.

Revision ID: 0015_participant_personas
Revises: 0014_loser_outbox
Create Date: 2026-06-09
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_participant_personas"
down_revision: str | Sequence[str] | None = "0014_loser_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "participant_personas",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("persona_text", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("participant_personas")
