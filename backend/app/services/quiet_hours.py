"""Тихие часы: ночью не будить базу без нужды.

Зачем это вообще нужно. Neon считает не «часы работы сервиса», а часы работы
compute. Планировщик живёт в том же процессе, что API, и дёргает базу каждые
5 минут (`meeting_reminders_tick`) и каждые 15 (`hr_tasks_tick`). Даже в полном
простое это 288 пробуждений в сутки, из-за чего `scale-to-zero` не срабатывает
никогда. 31.10.2026 квота free-плана подошла к 80 из 100 CU-часов — то есть
пилот с сотрудниками упёрся бы в отказ примерно через неделю
(разбор: `docs/NEON_BUDGET.md`).

Что делает этот модуль. В ночном окне задачи, ходящие в базу, выполняются не
чаще одного раза в `QUIET_TICK_MINUTES` (по умолчанию раз в час) вместо каждых
5 минут. Ресторан ночью не работает: напоминания, сроки поручений и сводки в
эти часы никому не нужны.

Важная деталь — **первый запуск в окне всегда выполняется**. Иначе контейнер,
поднятый в 02:00 (а деплой ночью — обычное дело), не отправил бы ни одного
напоминания до 07:00, хотя часть сроков уже просрочена. Лучше один лишний
проход по базе, чем пропущенная эскалация.

Настройка (без пересборки кода, переменными окружения):

* `QUIET_HOURS_START` — начало окна, час 0–23 (по умолчанию 23);
* `QUIET_HOURS_END` — конец окна, не включая (по умолчанию 7);
* `QUIET_TICK_MINUTES` — минимальный интервал внутри окна (по умолчанию 60).

Окно может переходить через полночь (`22 → 6`) и быть пустым
(`start == end` — тихие часы выключены).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_START_HOUR = 23
DEFAULT_END_HOUR = 7
DEFAULT_TICK_MINUTES = 60

# Когда каждая задача последний раз реально работала. Память, а не БД:
# хранить это в базе значило бы будить её ради экономии её же ресурса.
_LAST_RUN: dict[str, datetime] = {}


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def quiet_window() -> tuple[int, int, int]:
    """(начало, конец, интервал в минутах) с учётом переменных окружения."""
    start = min(23, max(0, _int_env("QUIET_HOURS_START", DEFAULT_START_HOUR)))
    end = min(24, max(0, _int_env("QUIET_HOURS_END", DEFAULT_END_HOUR)))
    tick = max(1, _int_env("QUIET_TICK_MINUTES", DEFAULT_TICK_MINUTES))
    return start, end, tick


def in_quiet_hours(
    now: datetime,
    start: int | None = None,
    end: int | None = None,
) -> bool:
    """Попадает ли момент в ночное окно.

    `start == end` означает «тихих часов нет»: иначе окно совпало бы с сутками
    и выключить прореживание стало бы невозможно.
    """
    if start is None or end is None:
        env_start, env_end, _tick = quiet_window()
        start = env_start if start is None else start
        end = env_end if end is None else end
    if start == end:
        return False
    hour = now.hour
    if start < end:
        return start <= hour < end
    # Окно через полночь: 23→7 значит «>=23 или <7».
    return hour >= start or hour < end


def _now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def should_run(job: str, *, now: datetime | None = None, tz: str = "UTC") -> bool:
    """Пора ли задаче работать (см. правило «первый запуск в окне всегда»)."""
    moment = now or _now(tz)
    if not in_quiet_hours(moment):
        _LAST_RUN[job] = moment
        return True
    _start, _end, tick = quiet_window()
    last = _LAST_RUN.get(job)
    if last is not None and moment - last < timedelta(minutes=tick):
        return False
    _LAST_RUN[job] = moment
    return True


def reset_state() -> None:
    """Сбросить память о прошлых запусках (для тестов и для рестарта)."""
    _LAST_RUN.clear()
