"""Ключ подписи ссылок на организацию: S-10/S-11.

Зачем. До этой миграции iCal и фото подписывались общим секретом контура:
смена ключа отзывала календари и фото у всех клиентов, а отозвать ссылку
одного уволенного сотрудника было нельзя. Теперь ключ принадлежит
организации, и ротация — её личное действие.

Почему `media_key_prev` и дата. Уже открытые вкладки и подключённые
календари нельзя гасить мгновенно: предыдущий ключ принимается 30 дней после
ротации, потом окно закрывается само — без второго выпуска кода.

Backfill: `random()` в Postgres даёт случайный ключ каждой существующей
организации. Это не секрет, который нельзя показывать, — в ссылку попадает
только HMAC, обратно ключ не восстанавливается. Но и логировать его незачем.

Revision ID: 0075_org_link_keys
Revises: 0074_org_branches
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0075_org_link_keys"
down_revision: str | None = "0074_org_branches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations", sa.Column("media_key", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "organizations",
        sa.Column("media_key_prev", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("media_key_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Две md5-строки — 64 hex-символа. `gen_random_uuid` потребовал бы
    # pgcrypto на старых контурах, а ключ — не UUID: важна длина и случайность.
    op.execute(
        "UPDATE organizations "
        "SET media_key = md5(random()::text) || md5(random()::text) "
        "WHERE media_key IS NULL"
    )


def downgrade() -> None:
    op.drop_column("organizations", "media_key_rotated_at")
    op.drop_column("organizations", "media_key_prev")
    op.drop_column("organizations", "media_key")
