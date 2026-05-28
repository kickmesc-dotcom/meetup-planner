"""GHG6 N2 — meeting_feedback: пост-фактум 5★ голосование по встрече.

На следующий день после `Meeting.starts_at` (для status='confirmed') бот
публикует Telegram-poll «Как собрались?» с 5-звёздочной шкалой + опцией
«меня не было». Голос записывается в `meeting_feedback`. Опция «меня не
было» поднимает `chukhan.weight.<tg_id>` на 0.5 (так пользователь сам
делает свой шанс попасть в чухан повыше).

Уникальность: (meeting_id, user_id) — каждый юзер голосует за одну встречу
один раз. Если в TG-опросе с anonymous=False, retract голоса пишется как
update; для anonymous=True мы получим только агрегат, но не персональный
голос — для шестёрки используем anonymous=False (см. services/meeting_feedback).

Поля:
- rating SMALLINT 1..5 — оценка по 5-звёздочной шкале (NULL если was_absent).
- was_absent BOOL — «меня не было» (rating должен быть NULL).
- reason_text TEXT NULL — необязательный комментарий (свободная форма).
- created_at — для сортировки и аудита.

Revision ID: 0013_meeting_feedback
Revises: 0012_loser_source
Create Date: 2026-05-27
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_meeting_feedback"
down_revision: str | Sequence[str] | None = "0012_loser_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meeting_feedback",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "meeting_id",
            sa.BigInteger(),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column(
            "was_absent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("meeting_id", "user_id", name="uq_feedback_meeting_user"),
        # CHECK: либо rating ∈ 1..5 (и was_absent=false), либо was_absent=true и
        # rating IS NULL. Никакого rating=0 или одновременно both-set.
        sa.CheckConstraint(
            "(was_absent = true AND rating IS NULL) OR "
            "(was_absent = false AND rating BETWEEN 1 AND 5)",
            name="ck_feedback_rating_or_absent",
        ),
    )
    op.alter_column(
        "meeting_feedback", "was_absent", server_default=None
    )
    op.create_index(
        "ix_feedback_meeting", "meeting_feedback", ["meeting_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_meeting", table_name="meeting_feedback")
    op.drop_table("meeting_feedback")
