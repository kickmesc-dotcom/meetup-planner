"""GHG10: чистые функции уровней и рангов.

Здесь НЕТ ни БД, ни сети — только арифметика над опытом (шаблон
`birthday_immunity.resolve_immune_pick`: логика отделена от I/O и тестируется
без сессии).

Все числа берутся из `config.py` — менять баланс нужно там, а не тут.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.game.config import (
    MAX_LEVEL,
    MIN_LEVEL,
    RANK_BY_LEVEL,
    SUPREME_CHUKHAN_TITLE,
    XP_PER_LEVEL,
    Rank,
)


def clamp_level(level: int) -> int:
    return max(MIN_LEVEL, min(MAX_LEVEL, level))


def level_for_xp(xp: int) -> int:
    """Уровень по накопленному опыту.

    1 уровень — от 0 XP. Каждый следующий — ещё `XP_PER_LEVEL`.
    На `MAX_LEVEL` останавливаемся: дальше опыт идёт в престиж (см.
    `prestige_for_xp`), а не в уровень.
    """
    if xp <= 0:
        return MIN_LEVEL
    return clamp_level(xp // XP_PER_LEVEL + 1)


def xp_into_level(xp: int) -> int:
    """Сколько опыта набрано внутри текущего уровня (для шкалы прогресса)."""
    if level_for_xp(xp) >= MAX_LEVEL:
        return XP_PER_LEVEL
    return max(0, xp - (level_for_xp(xp) - 1) * XP_PER_LEVEL)


def xp_to_next_level(xp: int) -> int | None:
    """Сколько опыта осталось до следующего уровня. `None` — уже максимум."""
    if level_for_xp(xp) >= MAX_LEVEL:
        return None
    return XP_PER_LEVEL - xp_into_level(xp)


def xp_cap() -> int:
    """Опыт, при котором достигается максимальный уровень.

    ⚠️ Именно `(MAX_LEVEL - 1) * XP_PER_LEVEL`, а не `MAX_LEVEL * XP_PER_LEVEL`:
    1 уровень — от 0 XP, поэтому 10 уровень начинается на 9 порогах (900), а не
    на 10 (1000). Иначе престиж стартовал бы, когда шкала ещё не заполнена.
    """
    return (MAX_LEVEL - 1) * XP_PER_LEVEL


def prestige_for_xp(xp: int) -> int:
    """Опыт сверх максимума → счётчик престижа.

    По заданию на 10 уровне прокачка прекращается, и «вся собранная экспа
    просто суммируется к счетчику очков престижа (который заменяет старую
    шкалу экспы/левела для данного юзера)».
    """
    return max(0, xp - xp_cap())


def rank_for_level(level: int) -> Rank:
    return RANK_BY_LEVEL[clamp_level(level)]


def rank_for_xp(xp: int) -> Rank:
    return rank_for_level(level_for_xp(xp))


@dataclass(frozen=True)
class Progress:
    """Всё, что нужно профилю для отрисовки, одним объектом."""

    xp: int
    level: int
    rank: Rank
    xp_into_level: int
    xp_to_next: int | None
    prestige: int
    at_max: bool


def progress_for_xp(xp: int) -> Progress:
    level = level_for_xp(xp)
    return Progress(
        xp=xp,
        level=level,
        rank=rank_for_level(level),
        xp_into_level=xp_into_level(xp),
        xp_to_next=xp_to_next_level(xp),
        prestige=prestige_for_xp(xp),
        at_max=level >= MAX_LEVEL,
    )


def levels_gained(old_xp: int, new_xp: int) -> list[int]:
    """Список уровней, взятых между двумя начислениями.

    Нужен для уведомления «какой ранг был, какой стал, что открылось»:
    одно начисление может закрыть сразу несколько уровней.
    """
    if new_xp <= old_xp:
        return []
    return list(
        range(level_for_xp(old_xp) + 1, level_for_xp(new_xp) + 1)
    )


def effective_rank_name(xp: int, *, supreme_chukhan: bool) -> str:
    """Название ранга с учётом спец-ранга.

    «Верховный чухан» — единственный ранг, который приоритетнее ранга за
    уровень (по заданию). Приходит он ачивкой-юбилеем, поэтому передаётся
    флагом, а не выводится из XP.
    """
    if supreme_chukhan:
        return SUPREME_CHUKHAN_TITLE
    return rank_for_xp(xp).name
