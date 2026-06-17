"""GHG8 T3.3: алёрты «лох/чухан не запостился в чат».

Прод-фидбек п.18: если в день назначения лоха/чухана не было поста в чатике —
нужен блок алёртов в админке (рядом с прокси), чтобы зашедшему лишний раз это
попало на глаза, плюс кнопка ручного перепрогона.

⚠️ Заморозка: этот модуль ТОЛЬКО ЧИТАЕТ БД (SELECT по loser_outbox/weekly_chukhan).
Никаких записей в outbox, никакого постинга. outbox лоха работает идеально и
никогда не зависает — мы его не трогаем, лишь показываем терминально-застрявшие
строки. Перепрогон есть ТОЛЬКО для чухана (у него нет outbox) и зовёт
существующую `retry_undelivered_chukhan` — см. routes_admin.

Критерий «пропуска» — ТЕРМИНАЛЬНЫЙ, чтобы не шуметь пока штатные ретраи идут:
- лох: `loser_outbox.status='expired'` (исчерпаны 12 попыток × 5 мин ≈ час);
- чухан: запись текущей недели с `posted_at IS NULL`, созданная > порога назад
  (ретрай чухана крутится каждые 30 мин — даём ему фору, прежде чем алёртить).

Чистые функции (is_chukhan_overdue, summarize) вынесены без БД-IO — их и тестируем.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Чухан: сколько ждать после создания записи (posted_at IS NULL), прежде чем
# считать пропуском. Ретрай-job чухана — каждые 30 мин; час даёт ≥1 попытку.
CHUKHAN_OVERDUE_AFTER = timedelta(hours=1)


def is_chukhan_overdue(
    created_at: datetime | None,
    posted_at: datetime | None,
    *,
    now: datetime | None = None,
    grace: timedelta = CHUKHAN_OVERDUE_AFTER,
) -> bool:
    """True если чухан назначен, но не запостился и фора уже вышла.

    posted_at не None → доставлен, не алёрт. created_at None (теоретически) →
    считаем свежим, не алёртим."""
    if posted_at is not None:
        return False
    if created_at is None:
        return False
    n = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return n - created_at >= grace


def summarize(loser_alerts: list[dict[str, Any]], chukhan_alert: dict[str, Any] | None) -> dict[str, Any]:
    """Собрать ответ с агрегатом. total — сколько всего поводов для внимания."""
    total = len(loser_alerts) + (1 if chukhan_alert else 0)
    return {
        "total": total,
        "loser": loser_alerts,
        "chukhan": chukhan_alert,
    }


async def get_posting_alerts(session: AsyncSession) -> dict[str, Any]:
    """Read-only: собрать терминально-незапостившиеся лох/чухан.

    Лох: loser_outbox.status='expired' (последние 20, свежие сверху). Чухан:
    запись текущей недели с posted_at IS NULL старше форы."""
    from app.db.models import LoserOutbox, LoserRoll, User, WeeklyChukhan
    from app.services.chukhan import current_week_start

    now = datetime.now(timezone.utc)

    # --- Лох: expired outbox-строки (только чтение) ---
    expired_rows = list(
        (
            await session.scalars(
                select(LoserOutbox)
                .where(LoserOutbox.status == "expired")
                .order_by(LoserOutbox.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    loser_alerts: list[dict[str, Any]] = []
    if expired_rows:
        roll_ids = [o.loser_roll_id for o in expired_rows]
        rolls = {
            r.id: r
            for r in (
                await session.scalars(
                    select(LoserRoll).where(LoserRoll.id.in_(roll_ids))
                )
            ).all()
        }
        user_ids = {r.loser_user_id for r in rolls.values()}
        names = {
            u.id: u.display_name
            for u in (
                await session.scalars(select(User).where(User.id.in_(user_ids)))
            ).all()
        } if user_ids else {}
        for o in expired_rows:
            roll = rolls.get(o.loser_roll_id)
            loser_alerts.append(
                {
                    "outbox_id": o.id,
                    "rolled_at": (
                        roll.rolled_at.isoformat() if roll and roll.rolled_at else None
                    ),
                    "loser_name": names.get(roll.loser_user_id) if roll else None,
                    "reason_text": roll.reason_text if roll else None,
                    "attempts": o.attempts,
                    "last_error": o.last_error,
                }
            )

    # --- Чухан: текущая неделя, posted_at IS NULL, старше форы ---
    chukhan_alert: dict[str, Any] | None = None
    ws = current_week_start(now)
    pending_chukhan = await session.scalar(
        select(WeeklyChukhan).where(
            WeeklyChukhan.week_start == ws,
            WeeklyChukhan.posted_at.is_(None),
        )
    )
    if pending_chukhan is not None and is_chukhan_overdue(
        pending_chukhan.created_at, pending_chukhan.posted_at, now=now
    ):
        chukhan_user = await session.scalar(
            select(User).where(User.id == pending_chukhan.user_id)
        )
        chukhan_alert = {
            "week_start": ws.isoformat(),
            "user_name": chukhan_user.display_name if chukhan_user else None,
            "created_at": (
                pending_chukhan.created_at.isoformat()
                if pending_chukhan.created_at
                else None
            ),
        }

    return summarize(loser_alerts, chukhan_alert)
