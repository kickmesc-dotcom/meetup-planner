"""Личные подписки на автоматические уведомления (жалоба владельца 04.11.2026).

Зачем. Утренняя сводка уходила всем руководителям организации по глобальному
тумблеру, включённому по умолчанию. Человек, которому она не нужна, не мог её
выключить — только просить администратора выключить всем. Это и есть спам:
сообщение приходит не потому, что ты его выбрал, а потому что тебя добавили.

Теперь на каждый вид автоматических сообщений есть личная подписка; по
умолчанию она **выключена**, и включить её может только сам человек — в
приложении или кнопкой под сообщением.

Почему отдельная таблица, а не ключ в `admin_config`. `admin_config` — это
настройки организации (одно значение на всех). Здесь значение на человека, и
оно удаляется вместе с человеком. Строка `(org_id, user_id, kind)` с
уникальным ключом даёт идемпотентную запись: повторное «включить» не плодит
дубли.

Revision ID: 0070_notify_prefs
Revises: 0069_api_integrations
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0070_notify_prefs"
down_revision: str | None = "0069_api_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notify_prefs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Вид сообщения: `digest` сегодня, дальше — напоминания и эскалации.
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "org_id", "user_id", "kind", name="uq_notify_pref_org_user_kind"
        ),
    )
    op.create_index("ix_notify_prefs_org_id", "notify_prefs", ["org_id"])
    op.create_index(
        "ix_notify_prefs_user", "notify_prefs", ["org_id", "user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_notify_prefs_user", table_name="notify_prefs")
    op.drop_index("ix_notify_prefs_org_id", table_name="notify_prefs")
    op.drop_table("notify_prefs")
