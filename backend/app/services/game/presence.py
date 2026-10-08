"""GHG11(10): присутствие участника в мини-аппе — «последний заход».

Прод-запрос: в чужом профиле внизу видно превью последней активности, в том
числе когда человек последний раз открывал мини-апп. По умолчанию показывается
у всех, у себя можно выключить (`ui.show_last_seen`).

Пишем метку из `/api/me` — это единственная ручка, которую фронт зовёт при
запуске приложения. Апдейт best-effort и троттлится в памяти процесса: `/api/me`
дёргается на каждый cold-start, а лишний `UPDATE` на Neon на горячем пути нам не
нужен. Троттлинг на процесс (а не на БД) выбран осознанно — при нескольких
воркерах будет несколько записи в 5 минут, это дёшево и не мешает точности
«последнего захода» (точность до минут, а не до секунд).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameProfile

log = structlog.get_logger()

# Не чаще одного UPDATE в 5 минут на процесс.
TOUCH_THROTTLE_SEC = 300
_touched_at: dict[int, float] = {}


def should_touch(
    user_id: int, *, now: float, throttle: int = TOUCH_THROTTLE_SEC
) -> bool:
    """Пора ли обновить метку захода (чистая функция — тестируется без БД)."""
    last = _touched_at.get(user_id)
    return last is None or (now - last) >= throttle


def reset_throttle() -> None:
    """Сбросить троттлинг (для тестов и ручных прогонов)."""
    _touched_at.clear()


async def touch_last_app_seen(
    session: AsyncSession, user_id: int, *, moment: datetime | None = None
) -> bool:
    """Отметить заход в мини-апп. True — метка записана.

    Best-effort: любой сбой (нет профиля, БД недоступна) только логируем —
    присутствие не стоит того, чтобы ломать `/api/me`.
    """
    mono = time.monotonic()
    if not should_touch(user_id, now=mono):
        return False
    _touched_at[user_id] = mono
    try:
        profile = await session.get(GameProfile, user_id)
        if profile is None:
            return False
        profile.last_app_seen_at = moment or datetime.now(timezone.utc)
        await session.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("presence.touch_failed", user_id=user_id, error=str(exc))
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False
