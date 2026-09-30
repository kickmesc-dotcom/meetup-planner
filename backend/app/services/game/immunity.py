"""GHG10 Э9: пожизненные иммунитеты за ранги 9 и 10.

Спека: «Девятый уровень — иммунитет к лоху НАВСЕГДА (с анонсом того, у кого
иммунитет, и от чего и в связи с чем). Десятый уровень — иммунитет к чухану
НАВСЕГДА».

Решения, которые стоит держать в голове:

1. **Порог не хардкожен.** Уровень берётся из `config.LEVEL_UNLOCKS` через
   `flags.required_level` — второго числа «9»/«10» в коде нет. Переставили
   `loser_immunity` на 8 уровень в конфиге — иммунитет поехал за ним.
2. **Иммунитет не хранится в БД.** Он выводится из опыта (`game_profiles.xp`),
   как и весь остальной ранг: нет миграции, нет рассинхрона «иммунитет есть, а
   ранга нет». Опыт откатили — иммунитет снялся сам.
3. **Рубильник главнее.** При `game.enabled=false` причин не возвращаем вовсе:
   сначала игра перестаёт давать опыт, потом гаснут её эффекты — иначе в чате
   остались бы «вечные неприкосновенные», которых нечем объяснить.
4. **Оглашение — общее.** Тексты собираются как `ImmuneReason` (см.
   `services/immunity.py`) и уезжают в тот же механизм, что и иммунитет
   именинника: один announce/silent-режим на все виды иммунитета.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameProfile, User
from app.services.game import levels
from app.services.game.config import feature_title
from app.services.game.flags import is_game_enabled, required_level
from app.services.immunity import (
    CHUKHAN_IMMUNITY,
    LOSER_IMMUNITY,
    ImmuneReason,
)

# Вид ролла → код фичи-иммунитета. Коды совпадают с теми, что лежат в
# `LEVEL_UNLOCKS`/`FEATURE_TITLES`, поэтому человеческий текст берётся оттуда.
IMMUNITY_FEATURES: dict[str, str] = {
    "loser": LOSER_IMMUNITY,
    "chukhan": CHUKHAN_IMMUNITY,
}


def immunity_level(kind: str) -> int | None:
    """С какого уровня этот вид ролла вообще может кого-то выбрать.

    `None` — такой вид иммунитета в конфиге не объявлен (иммунитетов нет).
    """
    return required_level(IMMUNITY_FEATURES[kind])


def immunity_threshold_xp(kind: str) -> int | None:
    """Минимум опыта, с которого иммунитет вообще возможен (для WHERE в SQL).

    Берём порог уровня из шкалы (`levels.xp_for_level`), а не считаем его числом:
    при смене шага шкалы (или переезде иммунитета на другой ранг) запрос иначе
    начал бы тянуть не тех.
    """
    level = immunity_level(kind)
    if level is None:
        return None
    return levels.xp_for_level(level)


def immunity_reason(level: int, kind: str) -> ImmuneReason:
    """Причина иммунитета для конкретного ранга (текст оглашения «в связи с чем»)."""
    code = IMMUNITY_FEATURES[kind]
    rank = levels.rank_for_level(level)
    return ImmuneReason(
        code,
        f"🎖 Мог бы стать <b>{{name}}</b>, но у него {level}-й ранг "
        f"«{rank.name}» — {feature_title(code).lower()}. Крутим заново…",
    )


async def rank_immune_reasons(
    session: AsyncSession, *, kind: str
) -> dict[int, ImmuneReason]:
    """user_id → причина иммунитета по рангу. Пусто, если игра выключена.

    Один SELECT и только по тем, у кого опыта уже хватает на пороговый уровень:
    точный уровень считает `levels.level_for_xp` (арифметику опыта SQL не
    дублирует — иначе при смене шкалы они разъедутся).
    """
    level_needed = immunity_level(kind)
    threshold = immunity_threshold_xp(kind)
    if level_needed is None or threshold is None:
        return {}
    if not await is_game_enabled(session):
        return {}

    rows = await session.execute(
        select(User.id, GameProfile.xp)
        .join(GameProfile, GameProfile.user_id == User.id)
        .where(GameProfile.xp >= threshold)
    )
    out: dict[int, ImmuneReason] = {}
    for user_id, xp in rows.all():
        level = levels.level_for_xp(xp)
        if level < level_needed:
            continue
        out[user_id] = immunity_reason(level, kind)
    return out
