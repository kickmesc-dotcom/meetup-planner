"""GHG7 P0.2 — loser_outbox: транзакционный outbox для авто-лоха.

Решение проблемы «запись в loser_rolls есть, поста в чате нет» — отделяем
domain (LoserRoll) от delivery (LoserOutbox). Автолох-job в scheduler пишет
запись в loser_rolls сразу и одновременно создаёт строку в loser_outbox со
status='pending'. Send в чат пробуется внутри той же транзакции; результат
(успех/ошибка) обновляет outbox-строку, но НЕ откатывает loser_roll.

Если первая попытка упала — отдельный scheduler-job `loser_outbox_retry`
раз в минуту повторяет SELECT ... FOR UPDATE SKIP LOCKED с лимитом 12
попыток (5 минут между ними → ~1 час суммарно). После 12 fails →
status='expired'.

calendar/marks фильтрует source='auto' loser-метки по статусу: показывает
только status='sent' OR outbox-записи нет (legacy до этой миграции). Так
корона на календаре появляется одновременно с постом в чат — без фантомов.

Ручные роллы (UI, chat-команда, admin force-reroll) outbox не пишут —
там best-effort send как было после GHG6 E3, юзер видит результат сам.

Revision ID: 0014_loser_outbox
Revises: 0013_meeting_feedback
Create Date: 2026-05-28
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_loser_outbox"
down_revision: str | Sequence[str] | None = "0013_meeting_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "loser_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "loser_roll_id",
            sa.BigInteger(),
            sa.ForeignKey("loser_rolls.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'expired')",
            name="ck_loser_outbox_status",
        ),
    )
    # снимаем server_default, чтобы ORM-вставки шли с явным значением, а
    # default остался только как fallback DDL — соответствует стилю
    # 0013_meeting_feedback с was_absent.
    op.alter_column("loser_outbox", "status", server_default=None)
    op.alter_column("loser_outbox", "attempts", server_default=None)
    # Покрывающий индекс для retry-job (SELECT ... WHERE status='pending'
    # AND next_retry_at <= now()).
    op.create_index(
        "ix_loser_outbox_pending",
        "loser_outbox",
        ["status", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_loser_outbox_pending", table_name="loser_outbox")
    op.drop_table("loser_outbox")
