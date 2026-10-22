"""Расписание по дням недели: «этот пункт — только по четвергам».

Зачем отдельный модуль. Дни недели нужны и чек-листам, и поручениям, и обоим
экранам (админке и сотруднику). Правило «строка `1,4` значит Пн и Чт» должно
жить в одном месте, иначе рано или поздно один экран посчитает воскресенье
седьмым днём, а другой — первым.

Формат строки: CSV из ISO-номеров (1 = понедельник … 7 = воскресенье).
Пустая строка и `NULL` одинаковы — «каждый день», как было до раунда 5.
"""

from __future__ import annotations

from datetime import date

# Подписи по ISO-номеру дня: 1 — понедельник.
WEEKDAY_SHORT: tuple[str, ...] = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
WEEKDAY_FULL: tuple[str, ...] = (
    "понедельникам",
    "вторникам",
    "средам",
    "четвергам",
    "пятницам",
    "субботам",
    "воскресеньям",
)
WEEKDAY_NAME: tuple[str, ...] = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)

WORKDAYS = (1, 2, 3, 4, 5)
WEEKEND = (6, 7)


def parse(value: str | None) -> tuple[int, ...]:
    """Строка из БД → отсортированный набор ISO-дней (пусто — каждый день).

    Мусор молча отбрасываем: ручное поле в админке не должно ломать выдачу
    чек-листа, если в него попала буква или `0`.
    """
    if not value:
        return ()
    seen: set[int] = set()
    for chunk in str(value).replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            day = int(chunk)
        except ValueError:
            continue
        if 1 <= day <= 7:
            seen.add(day)
    return tuple(sorted(seen))


def dump(days: list[int] | tuple[int, ...]) -> str | None:
    """Набор дней → строка для БД (пусто → `None` = каждый день)."""
    clean = sorted({day for day in days if 1 <= int(day) <= 7})
    return ",".join(str(day) for day in clean) or None


def is_active_on(value: str | None, day: date) -> bool:
    """Действует ли пункт в этот календарный день."""
    days = parse(value)
    return not days or day.isoweekday() in days


def is_every_day(value: str | None) -> bool:
    return not parse(value)


def label(value: str | None) -> str:
    """Человеческая подпись расписания: «по четвергам», «Пн, Ср, Пт»."""
    days = parse(value)
    if not days:
        return ""
    if len(days) == 7:
        return "каждый день"
    if days == WORKDAYS:
        return "по будням"
    if days == WEEKEND:
        return "по выходным"
    if len(days) == 1:
        return f"по {WEEKDAY_FULL[days[0] - 1]}"
    return ", ".join(WEEKDAY_SHORT[day - 1] for day in days)


def short(value: str | None) -> str:
    """Компактная подпись для чипа в списке: «Чт» или «Пн, Ср»."""
    days = parse(value)
    if not days or len(days) == 7:
        return ""
    if days == WORKDAYS:
        return "будни"
    if days == WEEKEND:
        return "выходные"
    return ", ".join(WEEKDAY_SHORT[day - 1] for day in days)


def next_active(value: str | None, today: date) -> date | None:
    """Ближайший день, когда пункт снова станет активным (None — уже активен)."""
    days = parse(value)
    if not days or today.isoweekday() in days:
        return None
    for shift in range(1, 8):
        candidate = date.fromordinal(today.toordinal() + shift)
        if candidate.isoweekday() in days:
            return candidate
    return None
