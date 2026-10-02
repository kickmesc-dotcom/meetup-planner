"""Э19: наблюдаемость игры — «сколько бот наработал за неделю».

Фидбек оператора: «сводка сколько событий/ответов/XP за неделю, чтобы видеть,
не спамит ли бот, без чтения чата». Модуль только ЧИТАЕТ существующие таблицы
(новых таблиц и миграций нет) и складывает один компактный словарь, который
отдаёт админская ручка.

Все запросы — по одному агрегату на источник (без N+1), окно — скользящие
`days` суток в UTC (та же шкала, что у `XpDaily`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    GameJournalEntry,
    GamePrompt,
    GameVoiceTask,
    UserAchievement,
    XpDaily,
)
from app.services.game.config import OBSERVABILITY_WINDOW_DAYS, XP_RULES


async def _count(session: AsyncSession, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model).where(*conditions)
    return int(await session.scalar(stmt) or 0)


async def summary(
    session: AsyncSession, *, days: int = OBSERVABILITY_WINDOW_DAYS, now: datetime | None = None
) -> dict:
    """Сводка активности игры за последние `days` суток.

    Ключи: `events`, `events_answered`, `voice_tasks`, `achievements_granted`,
    `digest_flushes`, `xp_total`, `by_event` (разбивка XP по событиям).
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    since = moment - timedelta(days=max(1, days))
    start_day = since.date()

    events = await _count(session, GamePrompt, GamePrompt.created_at >= since)
    events_answered = await _count(
        session,
        GamePrompt,
        GamePrompt.outcome == "won",
        GamePrompt.closed_at.is_not(None),
        GamePrompt.closed_at >= since,
    )
    voice_tasks = await _count(session, GameVoiceTask, GameVoiceTask.created_at >= since)
    achievements_granted = await _count(
        session, UserAchievement, UserAchievement.unlocked_at >= since
    )
    digest_flushes = int(
        await session.scalar(
            select(func.count(func.distinct(GameJournalEntry.sent_at))).where(
                GameJournalEntry.sent_at >= since
            )
        )
        or 0
    )

    rows = (
        await session.execute(
            select(
                XpDaily.event,
                func.sum(XpDaily.points),
                func.sum(XpDaily.count),
            )
            .where(XpDaily.day >= start_day)
            .group_by(XpDaily.event)
            .order_by(func.sum(XpDaily.points).desc())
        )
    ).all()
    by_event = []
    xp_total = 0
    for event, points, count in rows:
        rule = XP_RULES.get(event)
        by_event.append(
            {
                "event": event,
                "title": rule.title if rule else event,
                "points": int(points or 0),
                "count": int(count or 0),
            }
        )
        xp_total += int(points or 0)

    return {
        "window_days": days,
        "events": events,
        "events_answered": events_answered,
        "voice_tasks": voice_tasks,
        "achievements_granted": achievements_granted,
        "digest_flushes": digest_flushes,
        "xp_total": xp_total,
        "by_event": by_event,
    }
