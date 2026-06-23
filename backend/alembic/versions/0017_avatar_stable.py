"""GHG8 (18.06 #2) — стабильное хранение аватарок.

Прод-фидбег 18.06 #2: «приложуха забывает аватарки по прошествии времени».
Корень: `users.avatar_url` хранил TG file-URL с `file_path`, который живёт ≥1ч
и затем отдаёт 404 → <img> в мини-аппе ломается. Исключение Серж/Митян — у них
вручную подставлены ВНЕШНИЕ ссылки (не TG), они не протухают.

Фикс — храним стабильный `avatar_file_id` (не протухает) + прокси-роут резолвит
свежий file_path на лету; `avatar_manual_url` — ручная картинка (перекрывает TG
для отображения); `avatar_synced_at` — для меню «когда синкали».
Все три nullable: старые строки получают NULL, заполняются при синке/правке.
`avatar_url` оставлена как есть (читает frozen чухан-постинг).

Revision ID: 0017_avatar_stable
Revises: 0016_chukhan_reason
Create Date: 2026-06-18
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_avatar_stable"
down_revision: str | Sequence[str] | None = "0016_chukhan_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_file_id", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("avatar_manual_url", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("avatar_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_synced_at")
    op.drop_column("users", "avatar_manual_url")
    op.drop_column("users", "avatar_file_id")
