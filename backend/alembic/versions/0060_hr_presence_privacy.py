"""Присутствие и приватность сотрудника: «последний вход» и «последнее медиа».

Зачем в `employees`, а не в `admin_config`. Это свойство человека, а не
настройка бота: оно меняется из профиля, читается в карточке коллеги и живёт
ровно столько же, сколько рабочая строка. `last_seen_at` отдельный от
`auth_sessions.last_seen_at`: последний заход в приложение нужен и тем, кто
ходит только через Telegram-бота, а сессия у них не создаётся.

Оба переключателя по умолчанию включены — правило «показывай, пока человек
сам не попросил иначе». Руководство может запретить выключение: это решается
не здесь, а организационной политикой (`services/org_setup`).

Revision ID: 0060_hr_presence_privacy
Revises: 0059_email_verification
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0060_hr_presence_privacy"
down_revision: str | None = "0059_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column(
            "show_last_seen",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "employees",
        sa.Column(
            "show_last_media",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("employees", "show_last_media")
    op.drop_column("employees", "show_last_seen")
    op.drop_column("employees", "last_seen_at")
