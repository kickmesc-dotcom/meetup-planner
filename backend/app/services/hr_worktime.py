"""Рабочие часы ресторана и «тихие часы» уведомлений.

Зачем это отдельным модулем: правило «не будить управляющего в 03:41» должно
быть проверяемым без базы, планировщика и Telegram. Здесь только арифметика
времени, всё остальное — в `services/hr_settings.py` (хранение) и
`services/hr_reminders.py` (доставка).

Смена может пересекать полночь (ресторан закрывается в 02:00): окно
`open=10:00, close=02:00` считается «ночным» и разворачивается вокруг текущего
момента, а не сравнивается как два числа.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

# За сколько до открытия и после закрытия уведомления ещё разрешены.
DEFAULT_LEAD_MINUTES = 60
DEFAULT_TAIL_MINUTES = 60


def parse_hhmm(raw: str | None, default: time) -> time:
    """`"10:00"` → `time(10, 0)`. Мусор и пустое значение → дефолт."""
    if not raw:
        return default
    chunk = raw.strip()
    if ":" not in chunk:
        return default
    hh, _, mm = chunk.partition(":")
    try:
        hour, minute = int(hh), int(mm[:2])
    except ValueError:
        return default
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return time(hour, minute)
    return default


def format_hhmm(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def _combine(day: datetime, value: time) -> datetime:
    return day.replace(
        hour=value.hour, minute=value.minute, second=0, microsecond=0
    )


@dataclass(frozen=True)
class Window:
    """Разрешённый интервал уведомлений вокруг рабочей смены."""

    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end


def window_for(
    now: datetime,
    *,
    opens_at: time,
    closes_at: time,
    lead_minutes: int = DEFAULT_LEAD_MINUTES,
    tail_minutes: int = DEFAULT_TAIL_MINUTES,
) -> Window:
    """Окно уведомлений, в которое попадает `now`.

    Возвращает ближайшее окно: если сейчас раннее утро до открытия — это окно
    сегодняшней смены; если вечер и смена уже закрылась — окно, начавшееся
    вчера (с учётом `tail`), чтобы «ещё час после закрытия» работал честно.
    """
    lead = timedelta(minutes=max(0, lead_minutes))
    tail = timedelta(minutes=max(0, tail_minutes))
    overnight = closes_at <= opens_at

    start_today = _combine(now, opens_at) - lead
    close_day = now + timedelta(days=1) if overnight else now
    end_today = _combine(close_day, closes_at) + tail

    candidates = [Window(start_today, end_today)]
    # Вариант «смена началась вчера» — актуален для ночных ресторанов и для
    # момента сразу после закрытия (now < end_yesterday).
    yesterday = now - timedelta(days=1)
    start_yesterday = _combine(yesterday, opens_at) - lead
    end_yesterday = _combine(
        yesterday + timedelta(days=1) if overnight else yesterday, closes_at
    ) + tail
    candidates.append(Window(start_yesterday, end_yesterday))

    for window in candidates:
        if window.contains(now):
            return window
    # Вне окна: отдаём ближайшее будущее открытие, чтобы вызывающий код мог
    # сказать «напомним в 09:00», а не просто «нельзя».
    return Window(start_today, end_today)


def in_work_window(
    now: datetime,
    *,
    opens_at: time,
    closes_at: time,
    lead_minutes: int = DEFAULT_LEAD_MINUTES,
    tail_minutes: int = DEFAULT_TAIL_MINUTES,
) -> bool:
    return window_for(
        now,
        opens_at=opens_at,
        closes_at=closes_at,
        lead_minutes=lead_minutes,
        tail_minutes=tail_minutes,
    ).contains(now)
