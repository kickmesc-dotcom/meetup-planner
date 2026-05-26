"""GHG6 G3 — polls.is_closed для защиты от двойного срабатывания auto-close.

`record_poll_answer` при достижении кворума зовёт `force_close_poll`, который
делает `bot.stop_poll` и помечает строку `is_closed=True`. Без этого флага
второй голос сразу после первого мог бы повторно вызвать stop_poll (TG ответит
ошибкой, но всё равно лишний raund-trip).

Revision ID: 0011_poll_is_closed
Revises: 0010_games_nominations
Create Date: 2026-05-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_poll_is_closed"
down_revision: str | Sequence[str] | None = "0010_games_nominations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "polls",
        sa.Column(
            "is_closed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("polls", "is_closed")
