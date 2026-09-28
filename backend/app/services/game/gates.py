"""GHG10 Э8: гейтинг функций по рангам.

Задание открывает часть возможностей по рангу (рулетка лоха со 2-го, редактор
фраз лоха с 3-го, … иммунитеты на 9/10). Проверка — ДОПОЛНИТЕЛЬНЫЙ слой поверх
существующих прав, а не их замена (Э8: «гейтинг добавляется ТОЛЬКО как
дополнительная проверка поверх текущих прав админа»).

Три правила, зашитые здесь, чтобы их нельзя было забыть в точке вызова:

1. **Рубильник.** Если `game.enabled=false` — гейта НЕТ вообще. Иначе выключение
   игры заблокировало бы базовые функции бота, а это прямо запрещено (Э1:
   «в случае проблем — стопнуть модуль, не затронув остальную работу бота»).
2. **Отладка.** TG-id из `game.debug_tg_ids` («Серж нео») обходят любой гейт —
   иначе отладка новых функций была бы невозможна с 1 уровня.
3. **Реальный уровень** берётся из `game_profiles.xp` (уровень выводится из
   опыта, а не хранится). Нет профиля → 1 уровень.

Модуль отдаёт решение (`GateResult`) и текст отказа, а не бросает исключения:
API переводит отказ в HTTP 403, бот — в сообщение в чат. Так одна и та же
логика обслуживает обе поверхности.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.services.game.config import feature_title
from app.services.game.flags import (
    has_feature,
    is_debug_exempt,
    is_game_enabled,
    required_level,
)
from app.services.game.levels import level_for_xp
from app.services.game.xp import get_xp

# Префикс detail для HTTP 403: `rank_required:2`. Фронт распознаёт его и
# показывает человеческий текст (`humanizeApiError`), не парся локали.
RANK_REQUIRED = "rank_required"


@dataclass(frozen=True)
class GateResult:
    """Итог проверки: можно/нельзя + с какого ранга открылось бы."""

    allowed: bool
    feature: str
    level: int = 1
    required_level: int | None = None


async def check_feature(
    session: AsyncSession,
    feature: str,
    *,
    user_id: int | None = None,
    telegram_id: int | None = None,
) -> GateResult:
    """Доступна ли фича этому пользователю прямо сейчас.

    `user_id` (PK) предпочтителен; если его нет, но есть `telegram_id` —
    резолвим по `users`. Если нет ни того, ни другого — считаем 1 уровень.
    """
    if not await is_game_enabled(session):
        return GateResult(allowed=True, feature=feature)
    if await is_debug_exempt(session, telegram_id):
        return GateResult(allowed=True, feature=feature)

    uid = user_id
    if uid is None and telegram_id is not None:
        uid = await session.scalar(
            select(User.id).where(User.telegram_id == telegram_id)
        )
    level = level_for_xp(await get_xp(session, int(uid))) if uid is not None else 1
    return GateResult(
        allowed=has_feature(level, feature),
        feature=feature,
        level=level,
        required_level=required_level(feature),
    )


def denial_detail(res: GateResult) -> str:
    """Detail для HTTP 403: `rank_required:<N>` (`0` — если фича не гейтится)."""
    level = res.required_level if res.required_level is not None else 0
    return f"{RANK_REQUIRED}:{level}"


async def require_feature(session: AsyncSession, user, feature: str) -> None:
    """API-обёртка: 403 с `rank_required:<N>`, если ранг не дорос.

    FastAPI импортируется лениво, чтобы `gates` оставался вызываемым из бота
    без завязки на веб-слой.
    """
    from fastapi import HTTPException, status

    res = await check_feature(
        session, feature, user_id=user.id, telegram_id=user.telegram_id
    )
    if not res.allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, denial_detail(res))


def denial_message(res: GateResult) -> str:
    """Человеческий отказ для чата."""
    if res.required_level is None:
        return f"🔒 «{feature_title(res.feature)}» пока недоступно."
    return (
        f"🔒 «{feature_title(res.feature)}» открывается с {res.required_level} ранга. "
        "Качай опыт в чате и календаре."
    )
