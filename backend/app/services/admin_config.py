"""Runtime-настройки админа, перекрывающие env-vars.

Все P2-настройки (расписание, генератор фраз, автолох, тик напоминаний,
список фраз лоха) хранятся в таблице admin_config как key/value-строки.
Сложные структуры (например loser_reasons) — JSON-строкой.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import AdminConfig

CHUKHAN_WEIGHT_PREFIX = "chukhan_weight:"

# --- Random phrases (P1 уже было + P2 дополнения) ---
RANDOM_PHRASES_ENABLED_KEY = "random_phrases.enabled"
RANDOM_PHRASES_COUNT_KEY = "random_phrases.count"          # legacy: один N
RANDOM_PHRASES_COUNT_MIN_KEY = "random_phrases.count_min"  # A4: диапазон 2..6
RANDOM_PHRASES_COUNT_MAX_KEY = "random_phrases.count_max"
RANDOM_PHRASES_LOOKBACK_DAYS_KEY = "random_phrases.lookback_days"
RANDOM_PHRASES_COLLECTIVE_CHANCE_KEY = "random_phrases.collective_chance"
RANDOM_PHRASES_USER_CHANCE_KEY = "random_phrases.user_chance"
# A3: расписание автопостинга
RANDOM_PHRASES_SCHEDULE_MODE_KEY = "random_phrases.schedule_mode"   # daily_n|weekly_n|fixed_times|random_interval
RANDOM_PHRASES_SCHEDULE_PARAM_KEY = "random_phrases.schedule_param"  # JSON: {"n":3} | {"times":["12:00","18:00"]} | {"min_minutes":120}

# --- Reminders tick (A2) ---
REMINDERS_TICK_MINUTES_KEY = "reminders.tick_minutes"

# --- Loser reasons CRUD (A1) ---
LOSER_REASONS_KEY = "loser_reasons.list"

# --- Auto-loser (A6) ---
AUTOLOSER_ENABLED_KEY = "autoloser.enabled"
AUTOLOSER_WINDOW_START_HOUR_KEY = "autoloser.window_start_hour"  # default 7
AUTOLOSER_WINDOW_END_HOUR_KEY = "autoloser.window_end_hour"      # default 22
AUTOLOSER_INTERVAL_HOURS_KEY = "autoloser.interval_hours"        # 0 = random раз в сутки


async def _get_value(session: AsyncSession, key: str) -> str | None:
    row = await session.get(AdminConfig, key)
    return row.value if row else None


async def _set_value(session: AsyncSession, key: str, value: str) -> None:
    existing = await session.get(AdminConfig, key)
    if existing is None:
        session.add(AdminConfig(key=key, value=value))
    else:
        existing.value = value
    await session.commit()


async def get_random_phrases_enabled(session: AsyncSession) -> bool:
    raw = await _get_value(session, RANDOM_PHRASES_ENABLED_KEY)
    return (raw or "false").lower() in ("1", "true", "yes", "on")


async def set_random_phrases_enabled(session: AsyncSession, enabled: bool) -> None:
    await _set_value(session, RANDOM_PHRASES_ENABLED_KEY, "true" if enabled else "false")


async def get_random_phrases_count(session: AsyncSession) -> int:
    raw = await _get_value(session, RANDOM_PHRASES_COUNT_KEY)
    try:
        n = int(raw or "4")
    except ValueError:
        n = 4
    return max(2, min(6, n))


async def set_random_phrases_count(session: AsyncSession, count: int) -> None:
    await _set_value(
        session, RANDOM_PHRASES_COUNT_KEY, str(max(2, min(6, count)))
    )


async def get_chukhan_weights(session: AsyncSession) -> dict[int, float]:
    """Объединяет веса из env (база) и из admin_config (оверрайды)."""
    weights = dict(get_settings().chukhan_weight_map)
    rows = list(
        (
            await session.scalars(
                select(AdminConfig).where(
                    AdminConfig.key.startswith(CHUKHAN_WEIGHT_PREFIX)
                )
            )
        ).all()
    )
    for r in rows:
        try:
            tg_id = int(r.key[len(CHUKHAN_WEIGHT_PREFIX) :])
            weights[tg_id] = max(0.0, float(r.value))
        except (ValueError, TypeError):
            continue
    return weights


async def set_chukhan_weight(
    session: AsyncSession, *, tg_id: int, weight: float
) -> None:
    key = f"{CHUKHAN_WEIGHT_PREFIX}{tg_id}"
    existing = await session.get(AdminConfig, key)
    if existing is None:
        session.add(AdminConfig(key=key, value=str(weight)))
    else:
        existing.value = str(weight)
    await session.commit()


async def reset_chukhan_weight(session: AsyncSession, *, tg_id: int) -> None:
    key = f"{CHUKHAN_WEIGHT_PREFIX}{tg_id}"
    existing = await session.get(AdminConfig, key)
    if existing is not None:
        await session.delete(existing)
        await session.commit()


# --- Generic helpers ---

async def _get_int(session: AsyncSession, key: str, default: int) -> int:
    raw = await _get_value(session, key)
    try:
        return int(raw) if raw is not None else default
    except (ValueError, TypeError):
        return default


async def _get_float(session: AsyncSession, key: str, default: float) -> float:
    raw = await _get_value(session, key)
    try:
        return float(raw) if raw is not None else default
    except (ValueError, TypeError):
        return default


async def _get_bool(session: AsyncSession, key: str, default: bool) -> bool:
    raw = await _get_value(session, key)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


# --- A1: Loser reasons CRUD ---

def _default_loser_reasons() -> list[str]:
    # Импортируем лениво, чтобы избежать цикла (loser → admin_config → loser).
    from app.services.loser import LOSER_REASONS
    return list(LOSER_REASONS)


async def get_loser_reasons(session: AsyncSession) -> list[str]:
    """Возвращает кастомный список фраз лоха или дефолт из app.services.loser.

    Дефолтный список НЕ сохраняем в БД при чтении — это позволяет добавлять
    новые фразы в код и они подхватятся, пока админ не начал кастомизацию.
    """
    raw = await _get_value(session, LOSER_REASONS_KEY)
    if raw is None:
        return _default_loser_reasons()
    try:
        data = json.loads(raw)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data
    except (ValueError, TypeError):
        pass
    return _default_loser_reasons()


async def set_loser_reasons(session: AsyncSession, reasons: list[str]) -> None:
    # Дедуп + чистка пустых, не теряем порядок.
    seen: set[str] = set()
    cleaned: list[str] = []
    for r in reasons:
        r = r.strip()
        if not r or r in seen:
            continue
        seen.add(r)
        cleaned.append(r)
    await _set_value(session, LOSER_REASONS_KEY, json.dumps(cleaned, ensure_ascii=False))


# --- A2: Reminders tick ---

async def get_reminders_tick_minutes(session: AsyncSession) -> int:
    return max(1, min(120, await _get_int(session, REMINDERS_TICK_MINUTES_KEY, 10)))


async def set_reminders_tick_minutes(session: AsyncSession, minutes: int) -> None:
    await _set_value(
        session, REMINDERS_TICK_MINUTES_KEY, str(max(1, min(120, minutes)))
    )


# --- A3: Random phrases schedule ---

VALID_SCHEDULE_MODES = ("daily_n", "weekly_n", "fixed_times", "random_interval")


async def get_random_phrases_schedule(session: AsyncSession) -> tuple[str, dict]:
    mode = (await _get_value(session, RANDOM_PHRASES_SCHEDULE_MODE_KEY)) or "daily_n"
    if mode not in VALID_SCHEDULE_MODES:
        mode = "daily_n"
    raw = await _get_value(session, RANDOM_PHRASES_SCHEDULE_PARAM_KEY)
    try:
        param = json.loads(raw) if raw else {}
        if not isinstance(param, dict):
            param = {}
    except (ValueError, TypeError):
        param = {}
    return mode, param


async def set_random_phrases_schedule(
    session: AsyncSession, mode: str, param: dict
) -> None:
    if mode not in VALID_SCHEDULE_MODES:
        raise ValueError(f"bad schedule mode: {mode}")
    await _set_value(session, RANDOM_PHRASES_SCHEDULE_MODE_KEY, mode)
    await _set_value(
        session, RANDOM_PHRASES_SCHEDULE_PARAM_KEY, json.dumps(param, ensure_ascii=False)
    )


# --- A4: Generator settings ---

async def get_random_phrases_count_range(session: AsyncSession) -> tuple[int, int]:
    """A4: min..max кусочков в цитате. Бэк-совместимость: legacy count → min=max=count."""
    legacy = await _get_int(session, RANDOM_PHRASES_COUNT_KEY, 4)
    cmin = await _get_int(session, RANDOM_PHRASES_COUNT_MIN_KEY, legacy)
    cmax = await _get_int(session, RANDOM_PHRASES_COUNT_MAX_KEY, legacy)
    cmin = max(2, min(6, cmin))
    cmax = max(2, min(6, cmax))
    if cmin > cmax:
        cmin, cmax = cmax, cmin
    return cmin, cmax


async def set_random_phrases_count_range(
    session: AsyncSession, cmin: int, cmax: int
) -> None:
    cmin = max(2, min(6, cmin))
    cmax = max(2, min(6, cmax))
    if cmin > cmax:
        cmin, cmax = cmax, cmin
    await _set_value(session, RANDOM_PHRASES_COUNT_MIN_KEY, str(cmin))
    await _set_value(session, RANDOM_PHRASES_COUNT_MAX_KEY, str(cmax))
    # Старый ключ держим в синхроне для обратной совместимости.
    await _set_value(session, RANDOM_PHRASES_COUNT_KEY, str(cmax))


async def get_random_phrases_lookback_days(session: AsyncSession) -> int:
    return max(1, min(365, await _get_int(session, RANDOM_PHRASES_LOOKBACK_DAYS_KEY, 7)))


async def set_random_phrases_lookback_days(session: AsyncSession, days: int) -> None:
    await _set_value(
        session, RANDOM_PHRASES_LOOKBACK_DAYS_KEY, str(max(1, min(365, days)))
    )


async def get_random_phrases_collective_chance(session: AsyncSession) -> float:
    return max(0.0, min(1.0, await _get_float(session, RANDOM_PHRASES_COLLECTIVE_CHANCE_KEY, 0.1)))


async def set_random_phrases_collective_chance(session: AsyncSession, chance: float) -> None:
    await _set_value(
        session, RANDOM_PHRASES_COLLECTIVE_CHANCE_KEY, str(max(0.0, min(1.0, chance)))
    )


async def get_random_phrases_user_chance(session: AsyncSession) -> float:
    """Шанс того, что job вообще выстрелит (1.0 = всегда)."""
    return max(0.0, min(1.0, await _get_float(session, RANDOM_PHRASES_USER_CHANCE_KEY, 1.0)))


async def set_random_phrases_user_chance(session: AsyncSession, chance: float) -> None:
    await _set_value(
        session, RANDOM_PHRASES_USER_CHANCE_KEY, str(max(0.0, min(1.0, chance)))
    )


# --- A6: Auto-loser ---

async def get_autoloser_settings(session: AsyncSession) -> dict:
    return {
        "enabled": await _get_bool(session, AUTOLOSER_ENABLED_KEY, False),
        "window_start_hour": max(0, min(23, await _get_int(session, AUTOLOSER_WINDOW_START_HOUR_KEY, 7))),
        "window_end_hour": max(0, min(23, await _get_int(session, AUTOLOSER_WINDOW_END_HOUR_KEY, 22))),
        # 0 = random раз в сутки в окне; >0 = фиксированный интервал в часах.
        "interval_hours": max(0, min(72, await _get_int(session, AUTOLOSER_INTERVAL_HOURS_KEY, 0))),
    }


async def set_autoloser_settings(
    session: AsyncSession,
    *,
    enabled: bool,
    window_start_hour: int,
    window_end_hour: int,
    interval_hours: int,
) -> None:
    await _set_value(session, AUTOLOSER_ENABLED_KEY, "true" if enabled else "false")
    await _set_value(
        session, AUTOLOSER_WINDOW_START_HOUR_KEY, str(max(0, min(23, window_start_hour)))
    )
    await _set_value(
        session, AUTOLOSER_WINDOW_END_HOUR_KEY, str(max(0, min(23, window_end_hour)))
    )
    await _set_value(
        session, AUTOLOSER_INTERVAL_HOURS_KEY, str(max(0, min(72, interval_hours)))
    )
