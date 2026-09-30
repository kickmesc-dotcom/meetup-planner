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
    XP_CURVE_STEP,
    Rank,
)


def clamp_level(level: int) -> int:
    return max(MIN_LEVEL, min(MAX_LEVEL, level))


def xp_for_level(level: int) -> int:
    """Сколько ВСЕГО опыта нужно, чтобы начать этот уровень.

    1 уровень — 0 XP. Каждый следующий переход дороже: переход «N → N+1» стоит
    `XP_CURVE_STEP * N` (100 / 200 / 300 / …), поэтому пороги — треугольные
    числа, умноженные на шаг:

        0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500

    Чистая функция (тесты без БД). Уровень ниже первого трактуем как первый.
    """
    lvl = max(0, level)
    return XP_CURVE_STEP * (lvl - 1) * lvl // 2


def xp_span_for_level(level: int) -> int:
    """Сколько XP стоит переход С этого уровня на следующий.

    Нужно шкале прогресса: её знаменатель — не «цена любого уровня», а цена
    именно текущего перехода (иначе шкала на 8 уровне заполнялась бы за 100 XP).
    """
    return XP_CURVE_STEP * clamp_level(level)


def level_for_xp(xp: int) -> int:
    """Уровень по накопленному опыту (прогрессивная шкала).

    На `MAX_LEVEL` останавливаемся: дальше опыт идёт в престиж (см.
    `prestige_for_xp`), а не в уровень. Порогов всего 10, поэтому простой
    подъём по ним — и честнее, и быстрее любой «магии» с формулой.
    """
    if xp <= 0:
        return MIN_LEVEL
    level = MIN_LEVEL
    while level < MAX_LEVEL and xp >= xp_for_level(level + 1):
        level += 1
    return level


def xp_into_level(xp: int) -> int:
    """Сколько опыта набрано внутри текущего уровня (для шкалы прогресса)."""
    level = level_for_xp(xp)
    if level >= MAX_LEVEL:
        return xp_span_for_level(MAX_LEVEL)
    return max(0, xp - xp_for_level(level))


def xp_to_next_level(xp: int) -> int | None:
    """Сколько опыта осталось до следующего уровня. `None` — уже максимум."""
    level = level_for_xp(xp)
    if level >= MAX_LEVEL:
        return None
    return xp_for_level(level + 1) - xp


def xp_cap() -> int:
    """Опыт, при котором достигается максимальный уровень.

    Это порог 10 уровня (4500 при шаге 100), а не сумма «цена × уровни»:
    1 уровень начинается с 0 XP, поэтому порог уровня L — сумма L-1 переходов.
    Иначе престиж стартовал бы, когда шкала ещё не заполнена.
    """
    return xp_for_level(MAX_LEVEL)


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
