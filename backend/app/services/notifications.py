"""GHG11(9): личные уведомления внутри мини-аппа.

В чат такие события не ходят — лайк чужого трека шестёрке не новость, а автора
услышать надо. Поэтому уведомление кладётся строкой в `app_notifications` и
показывается в приложении колокольчиком с бейджем непрочитанных.

Сервис тонкий и без побочных эффектов: `add` только добавляет строку в текущую
транзакцию (коммит — на совести вызывающего, обычно он уже есть), остальные —
простые выборки. Текст собирает вызывающий: сервис не знает про музыкальные
подписи и не тянет за собой лишние зависимости.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppNotification

# Типы уведомлений. Пока один: кто-то лайкнул твой трек.
KIND_MUSIC_LIKE = "music_like"

# Сколько уведомлений отдаём в колокольчик по умолчанию.
NOTIFICATIONS_LIMIT = 30


async def add(
    session: AsyncSession,
    *,
    user_id: int,
    kind: str,
    text: str,
    payload: dict | None = None,
) -> AppNotification:
    """Добавить уведомление получателю. Коммитит ВЫЗЫВАЮЩИЙ.

    Именно так: лайк и уведомление — одна транзакция, иначе можно получить
    уведомление без лайка (или наоборот) при откате.
    """
    row = AppNotification(
        user_id=user_id,
        kind=kind,
        text=text,
        payload=dict(payload or {}),
    )
    session.add(row)
    return row


async def list_for_user(
    session: AsyncSession, user_id: int, *, limit: int = NOTIFICATIONS_LIMIT
) -> list[AppNotification]:
    """Свежие уведомления сверху. Порядок устойчив: `id` как второй ключ."""
    rows = await session.scalars(
        select(AppNotification)
        .where(AppNotification.user_id == user_id)
        .order_by(AppNotification.created_at.desc(), AppNotification.id.desc())
        .limit(limit)
    )
    return list(rows)


async def unread_count(session: AsyncSession, user_id: int) -> int:
    """Сколько непрочитанных — для бейджа на колокольчике."""
    count = await session.scalar(
        select(func.count())
        .select_from(AppNotification)
        .where(
            AppNotification.user_id == user_id,
            AppNotification.read_at.is_(None),
        )
    )
    return int(count or 0)


async def mark_read(
    session: AsyncSession,
    user_id: int,
    *,
    ids: list[int] | None = None,
    all_: bool = False,
) -> int:
    """Отметить прочитанными конкретные уведомления или все сразу.

    Возвращает, сколько строк реально изменилось. Чужие уведомления отметить
    нельзя: `user_id` — часть условия (id приходит с клиента, ему нельзя верить),
    повторная отметка уже прочитанного — no-op, а не ошибка.
    """
    now = datetime.now(timezone.utc)
    stmt = update(AppNotification).where(
        AppNotification.user_id == user_id,
        AppNotification.read_at.is_(None),
    )
    if not all_:
        if not ids:
            return 0
        stmt = stmt.where(AppNotification.id.in_(ids))
    result = await session.execute(stmt.values(read_at=now))
    await session.commit()
    return int(result.rowcount or 0)
