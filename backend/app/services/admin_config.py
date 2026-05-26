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

# --- E8: «Червь-пидор» (особая номинация при ролле лоха) ---
WORM_ENABLED_KEY = "worm.enabled"          # default true (механика работает)
WORM_CHANCE_KEY = "worm.chance"            # default 0.01 (1/100)

# Хардкод-дефолты — чтобы можно было выкатить фичу без миграции конфига.
_WORM_ENABLED_DEFAULT = True
_WORM_CHANCE_DEFAULT = 0.01

# --- G2/G3: настройки опросов в чате ---
# G2: закрепление сообщения с опросом после публикации
POLLS_PIN_DEFAULT_KEY = "polls.pin_default"              # default False
# G3: авто-закрытие при достижении кворума
POLLS_QUORUM_AUTO_CLOSE_KEY = "polls.quorum_auto_close"  # default True
POLLS_LIVE_PARTICIPANTS_KEY = "polls.live_participants_count"  # default 5
POLLS_PIN_RESULT_KEY = "polls.pin_result"                # default False (пин announce-сообщения)

_POLLS_PIN_DEFAULT_DEFAULT = False
_POLLS_QUORUM_AUTO_CLOSE_DEFAULT = True
_POLLS_LIVE_PARTICIPANTS_DEFAULT = 5
_POLLS_PIN_RESULT_DEFAULT = False


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
    # GHG6 E5: дроп счётчиков для фраз, которых больше нет в активном списке.
    # Lazy-импорт во избежание цикла admin_config ↔ phrase_weights.
    from app.services.phrase_weights import LOSER_USE_COUNTS_KEY, cleanup_use_counts
    await cleanup_use_counts(session, LOSER_USE_COUNTS_KEY, cleaned)


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


# --- GHG5 POLL-HOURS1: Human-friendly time presets for polls/auto-pick ---

POLL_TIME_PRESETS_KEY = "poll.time_presets"

DEFAULT_POLL_TIME_PRESETS: list[dict] = [
    {"start": "12:00", "end": "15:00"},
    {"start": "15:00", "end": "18:00"},
    {"start": "18:00", "end": "20:00"},
    {"start": "20:00", "end": "23:00"},
]


def _validate_preset_dict(p: object) -> dict | None:
    if not isinstance(p, dict):
        return None
    s = p.get("start")
    e = p.get("end")
    if not isinstance(s, str) or not isinstance(e, str):
        return None
    try:
        sh, sm = (int(x) for x in s.split(":"))
        eh, em = (int(x) for x in e.split(":"))
    except (ValueError, AttributeError):
        return None
    if not (0 <= sh <= 23 and 0 <= sm <= 59 and 0 <= eh <= 23 and 0 <= em <= 59):
        return None
    if (sh, sm) >= (eh, em):
        return None
    label = p.get("label")
    out = {"start": f"{sh:02d}:{sm:02d}", "end": f"{eh:02d}:{em:02d}"}
    if isinstance(label, str) and label.strip():
        out["label"] = label.strip()[:32]
    return out


async def get_poll_time_presets(session: AsyncSession) -> list[dict]:
    raw = await _get_value(session, POLL_TIME_PRESETS_KEY)
    if raw is None:
        return [dict(p) for p in DEFAULT_POLL_TIME_PRESETS]
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return [dict(p) for p in DEFAULT_POLL_TIME_PRESETS]
    if not isinstance(data, list):
        return [dict(p) for p in DEFAULT_POLL_TIME_PRESETS]
    out: list[dict] = []
    for item in data:
        v = _validate_preset_dict(item)
        if v is not None:
            out.append(v)
    return out or [dict(p) for p in DEFAULT_POLL_TIME_PRESETS]


async def set_poll_time_presets(session: AsyncSession, presets: list[dict]) -> None:
    cleaned: list[dict] = []
    for p in presets:
        v = _validate_preset_dict(p)
        if v is not None:
            cleaned.append(v)
    if not cleaned:
        # Не даём «обнулить в ноль» — слотов не будет совсем.
        cleaned = [dict(p) for p in DEFAULT_POLL_TIME_PRESETS]
    await _set_value(session, POLL_TIME_PRESETS_KEY, json.dumps(cleaned, ensure_ascii=False))


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


# =============================================================================
# GHG6 P2: chukhan-фразы + master-toggles периодических процессов
# =============================================================================


# --- AD6: chukhan_reasons (по образцу loser_reasons) ---

CHUKHAN_REASONS_KEY = "chukhan_reasons.list"

_DEFAULT_CHUKHAN_REASONS: list[str] = [
    "за немытую кружку на столе",
    "за опоздание больше чем на 15 минут",
    "за рассказ про крипту в нерабочее время",
    "за чужие наушники без спроса",
    "за «потом доделаю» на ретроспективе",
    "за пропуск встречи без отмены",
]


# --- CL0: новый таймлайн-вид календаря (master-toggle) ---

CALENDAR_TIMELINE_ENABLED_KEY = "calendar.timeline_enabled"


async def get_calendar_timeline_enabled(session: AsyncSession) -> bool:
    """GHG6 CL0: глобальный switch «новый таймлайн или legacy-вид».

    Default = False (пока этапы 2-4 не доделаны — нет жестов, зума, нижней
    плашки). Включается админкой через
    `PUT /admin/calendar/timeline {enabled:true}` для ручного теста.
    Когда CL2/CL3/CL5/CL13 приземлятся, дефолт станет True.
    """
    return await _get_bool(session, CALENDAR_TIMELINE_ENABLED_KEY, False)


async def set_calendar_timeline_enabled(session: AsyncSession, enabled: bool) -> None:
    await _set_value(
        session, CALENDAR_TIMELINE_ENABLED_KEY, "true" if enabled else "false"
    )


# --- BD2: Birthdays greeting templates ---

BIRTHDAYS_GREETING_TEMPLATES_KEY = "birthdays.greeting_templates"

_DEFAULT_BIRTHDAY_GREETINGS: list[str] = [
    "С днём рождения, {name}! 🎉 Пусть {age_or_year} принесёт побольше движа и поменьше дедлайнов.",
    "{name}, расти большим! 🎂 {age_phrase} — самое время устроить движ всей шестёркой.",
    "С др, {name}! Здоровья, бабла и нормальных собутыльников. {age_phrase} 🥂",
    "Сегодня {name} стал на год старше и на пиво ближе к мудрости. {age_phrase} 🍻",
    "{name}, шестёрка тебя поздравляет! 🎊 {age_phrase} Пусть тосты будут громче, а похмелье — мягче.",
    "С праздником, {name}! 🎁 Желаем меньше «под вопросом» в календаре. {age_phrase}",
]


async def get_birthdays_greeting_templates(session: AsyncSession) -> list[str]:
    """Список шаблонов поздравлений с плейсхолдерами {name}/{age}/{age_phrase}/{age_or_year}.

    Шаблон БЕЗ кастомного списка → дефолтный набор из кода. После того как
    админ сохранит свой набор, дефолт перестаёт «протекать».
    """
    raw = await _get_value(session, BIRTHDAYS_GREETING_TEMPLATES_KEY)
    if raw is None:
        return list(_DEFAULT_BIRTHDAY_GREETINGS)
    try:
        data = json.loads(raw)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data or list(_DEFAULT_BIRTHDAY_GREETINGS)
    except (ValueError, TypeError):
        pass
    return list(_DEFAULT_BIRTHDAY_GREETINGS)


async def set_birthdays_greeting_templates(
    session: AsyncSession, templates: list[str]
) -> None:
    seen: set[str] = set()
    cleaned: list[str] = []
    for t in templates:
        t = t.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        cleaned.append(t)
    await _set_value(
        session,
        BIRTHDAYS_GREETING_TEMPLATES_KEY,
        json.dumps(cleaned, ensure_ascii=False),
    )


async def get_chukhan_reasons(session: AsyncSession) -> list[str]:
    raw = await _get_value(session, CHUKHAN_REASONS_KEY)
    if raw is None:
        return list(_DEFAULT_CHUKHAN_REASONS)
    try:
        data = json.loads(raw)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data
    except (ValueError, TypeError):
        pass
    return list(_DEFAULT_CHUKHAN_REASONS)


async def set_chukhan_reasons(session: AsyncSession, reasons: list[str]) -> None:
    seen: set[str] = set()
    cleaned: list[str] = []
    for r in reasons:
        r = r.strip()
        if not r or r in seen:
            continue
        seen.add(r)
        cleaned.append(r)
    await _set_value(
        session, CHUKHAN_REASONS_KEY, json.dumps(cleaned, ensure_ascii=False)
    )
    # GHG6 E5: дроп счётчиков для фраз, которых больше нет в активном списке.
    from app.services.phrase_weights import CHUKHAN_USE_COUNTS_KEY, cleanup_use_counts
    await cleanup_use_counts(session, CHUKHAN_USE_COUNTS_KEY, cleaned)


# --- AD6: master-toggles для запланированных процессов ---

# reminders уже есть (REMINDERS_TICK_MINUTES_KEY). Добавляем enabled:
REMINDERS_ENABLED_KEY = "reminders.enabled"

# loser auto: уже есть AUTOLOSER_*_KEY. Добавим per_day (для совместимости с UI).
LOSER_AUTO_PER_DAY_KEY = "loser.auto.per_day"

# phrases auto: уже есть RANDOM_PHRASES_ENABLED_KEY. Добавим окно активности и
# per_day для согласованности с UI (фактически это переключатель на daily_n).
PHRASES_WINDOW_START_KEY = "random_phrases.window_start"  # "HH:MM"
PHRASES_WINDOW_END_KEY = "random_phrases.window_end"      # "HH:MM"

# avatars sync
AVATARS_SYNC_ENABLED_KEY = "avatars.sync_enabled"
AVATARS_SYNC_PER_DAY_KEY = "avatars.sync_per_day"  # float, >=0.14 (раз в неделю)

# birthdays — глобальный switch
BIRTHDAYS_ALERTS_ENABLED_KEY = "birthdays.alerts_enabled"

# chukhan weekly publish window
CHUKHAN_WEEKDAY_KEY = "chukhan.weekday"            # int 0..6 (0=пн)
CHUKHAN_WINDOW_START_KEY = "chukhan.window_start"  # "HH:MM"
CHUKHAN_WINDOW_END_KEY = "chukhan.window_end"      # "HH:MM"


def _validate_hhmm(s: str | None, default: str) -> str:
    if not isinstance(s, str):
        return default
    try:
        h, m = (int(x) for x in s.strip().split(":"))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    except (ValueError, AttributeError):
        pass
    return default


async def _get_hhmm(session: AsyncSession, key: str, default: str) -> str:
    raw = await _get_value(session, key)
    return _validate_hhmm(raw, default)


async def get_scheduled_settings(session: AsyncSession) -> dict:
    """Агрегат настроек запланированных публикаций — для UI и для scheduler."""
    auto = await get_autoloser_settings(session)
    return {
        "reminders": {
            "enabled": await _get_bool(session, REMINDERS_ENABLED_KEY, True),
            "tick_minutes": await get_reminders_tick_minutes(session),
        },
        "loser": {
            "enabled": auto["enabled"],
            "per_day": max(1, min(12, await _get_int(session, LOSER_AUTO_PER_DAY_KEY, 1))),
            "window_start_hour": auto["window_start_hour"],
            "window_end_hour": auto["window_end_hour"],
            "interval_hours": auto["interval_hours"],
        },
        "phrases": {
            "enabled": await get_random_phrases_enabled(session),
            "window_start": await _get_hhmm(session, PHRASES_WINDOW_START_KEY, "07:30"),
            "window_end": await _get_hhmm(session, PHRASES_WINDOW_END_KEY, "22:00"),
        },
        "avatars": {
            # E10 (GHG6, 2026-05-22): default → false. Рекуррентный авто-синхрон
            # упразднён, в UI остались только разовая кнопка и одноразовое расписание.
            # `per_day` оставлен в схеме для обратной совместимости со старой записью
            # в admin_config, но UI его больше не показывает и не редактирует.
            "enabled": await _get_bool(session, AVATARS_SYNC_ENABLED_KEY, False),
            "per_day": max(
                0.14, min(24.0, await _get_float(session, AVATARS_SYNC_PER_DAY_KEY, 1.0))
            ),
        },
        "birthdays": {
            "alerts_enabled": await _get_bool(session, BIRTHDAYS_ALERTS_ENABLED_KEY, True),
        },
        "chukhan": {
            "weekday": max(0, min(6, await _get_int(session, CHUKHAN_WEEKDAY_KEY, 0))),
            "window_start": await _get_hhmm(session, CHUKHAN_WINDOW_START_KEY, "07:30"),
            "window_end": await _get_hhmm(session, CHUKHAN_WINDOW_END_KEY, "12:00"),
        },
    }


async def set_scheduled_settings(session: AsyncSession, body: dict) -> None:
    """Принимает структуру get_scheduled_settings и сохраняет все ключи.

    Идемпотентно. После записи вызывающий должен дёрнуть
    `scheduler.reload_dynamic_jobs(bot)` чтобы новые значения подхватились.
    """
    rem = body.get("reminders") or {}
    if "enabled" in rem:
        await _set_value(
            session, REMINDERS_ENABLED_KEY, "true" if rem["enabled"] else "false"
        )
    if "tick_minutes" in rem:
        await set_reminders_tick_minutes(session, int(rem["tick_minutes"]))

    loser = body.get("loser") or {}
    if loser:
        # Конвертируем per_day → interval_hours, если оба заданы:
        # per_day=1 → interval=0 (random); per_day≥2 → interval = 24 / per_day.
        per_day = int(loser.get("per_day", 1))
        interval = 0 if per_day <= 1 else max(1, 24 // per_day)
        await set_autoloser_settings(
            session,
            enabled=bool(loser.get("enabled", False)),
            window_start_hour=int(loser.get("window_start_hour", 7)),
            window_end_hour=int(loser.get("window_end_hour", 22)),
            interval_hours=int(loser.get("interval_hours", interval)),
        )
        await _set_value(session, LOSER_AUTO_PER_DAY_KEY, str(max(1, min(12, per_day))))

    phrases = body.get("phrases") or {}
    if "enabled" in phrases:
        await set_random_phrases_enabled(session, bool(phrases["enabled"]))
    if "window_start" in phrases:
        await _set_value(
            session,
            PHRASES_WINDOW_START_KEY,
            _validate_hhmm(phrases["window_start"], "07:30"),
        )
    if "window_end" in phrases:
        await _set_value(
            session, PHRASES_WINDOW_END_KEY, _validate_hhmm(phrases["window_end"], "22:00")
        )

    avatars = body.get("avatars") or {}
    if "enabled" in avatars:
        await _set_value(
            session,
            AVATARS_SYNC_ENABLED_KEY,
            "true" if avatars["enabled"] else "false",
        )
    if "per_day" in avatars:
        per = max(0.14, min(24.0, float(avatars["per_day"])))
        await _set_value(session, AVATARS_SYNC_PER_DAY_KEY, str(per))

    birthdays = body.get("birthdays") or {}
    if "alerts_enabled" in birthdays:
        await _set_value(
            session,
            BIRTHDAYS_ALERTS_ENABLED_KEY,
            "true" if birthdays["alerts_enabled"] else "false",
        )

    chukhan = body.get("chukhan") or {}
    if "weekday" in chukhan:
        await _set_value(
            session,
            CHUKHAN_WEEKDAY_KEY,
            str(max(0, min(6, int(chukhan["weekday"])))),
        )
    if "window_start" in chukhan:
        await _set_value(
            session,
            CHUKHAN_WINDOW_START_KEY,
            _validate_hhmm(chukhan["window_start"], "07:30"),
        )
    if "window_end" in chukhan:
        await _set_value(
            session,
            CHUKHAN_WINDOW_END_KEY,
            _validate_hhmm(chukhan["window_end"], "12:00"),
        )


# --- E8: «Червь-пидор» ---

async def is_worm_enabled(session: AsyncSession) -> bool:
    raw = await _get_value(session, WORM_ENABLED_KEY)
    if raw is None:
        return _WORM_ENABLED_DEFAULT
    return raw.lower() in ("1", "true", "yes", "on")


async def set_worm_enabled(session: AsyncSession, enabled: bool) -> None:
    await _set_value(session, WORM_ENABLED_KEY, "true" if enabled else "false")


async def get_worm_chance(session: AsyncSession) -> float:
    """Шанс выпадения червя при ролле лоха. Clamp [0..1]."""
    raw = await _get_value(session, WORM_CHANCE_KEY)
    if raw is None:
        return _WORM_CHANCE_DEFAULT
    try:
        v = float(raw)
    except (ValueError, TypeError):
        return _WORM_CHANCE_DEFAULT
    return max(0.0, min(1.0, v))


async def set_worm_chance(session: AsyncSession, chance: float) -> None:
    v = max(0.0, min(1.0, float(chance)))
    await _set_value(session, WORM_CHANCE_KEY, f"{v:.6f}")


# --- E9: реакции бота на @-mention и reply ---
# Три независимых master-toggle (см. GHG6.txt п.9):
#  - mention_enabled         — @bot в чате → ответ. Default ON.
#  - reply_all_enabled       — reply на ЛЮБОЕ сообщение бота → ответ. Default OFF.
#  - reply_except_phrases_enabled — reply на сообщение бота, КРОМЕ рандом-цитат
#    → ответ. Default ON.
# Логика срабатывания (в bot_reactions handler): сначала проверяем
# reply_all_enabled (отвечает на всё подряд), затем reply_except_phrases_enabled
# (отвечает только если оригинал НЕ цитата). Это две отдельные ветки, чтобы
# можно было гонять «отвечать на всё» и «отвечать на не-цитаты» независимо.
BOT_REACT_MENTION_KEY = "bot_reactions.mention_enabled"                  # default true
BOT_REACT_REPLY_ALL_KEY = "bot_reactions.reply_all_enabled"              # default false
BOT_REACT_REPLY_EXCEPT_PHRASES_KEY = "bot_reactions.reply_except_phrases_enabled"  # default true


async def get_bot_reactions_settings(session: AsyncSession) -> dict:
    """Агрегат для UI: одна запись API на все три флага."""
    return {
        "mention_enabled": await _get_bool(session, BOT_REACT_MENTION_KEY, True),
        "reply_all_enabled": await _get_bool(
            session, BOT_REACT_REPLY_ALL_KEY, False
        ),
        "reply_except_phrases_enabled": await _get_bool(
            session, BOT_REACT_REPLY_EXCEPT_PHRASES_KEY, True
        ),
    }


async def set_bot_reactions_settings(
    session: AsyncSession,
    *,
    mention_enabled: bool | None = None,
    reply_all_enabled: bool | None = None,
    reply_except_phrases_enabled: bool | None = None,
) -> None:
    if mention_enabled is not None:
        await _set_value(
            session, BOT_REACT_MENTION_KEY, "true" if mention_enabled else "false"
        )
    if reply_all_enabled is not None:
        await _set_value(
            session,
            BOT_REACT_REPLY_ALL_KEY,
            "true" if reply_all_enabled else "false",
        )
    if reply_except_phrases_enabled is not None:
        await _set_value(
            session,
            BOT_REACT_REPLY_EXCEPT_PHRASES_KEY,
            "true" if reply_except_phrases_enabled else "false",
        )


# --- E7: per-user UI prefs (закрываемое приветствие) ---
# Хранятся как `ui.hide_greeting:{tg_id}` -> "true"/"false". Per-user, потому что
# баннер приветствия каждый прячет себе сам. tg_id (а не user.id) — стабильный
# идентификатор от Telegram, ему доверяем больше, чем нашему автоинкременту.
UI_HIDE_GREETING_PREFIX = "ui.hide_greeting:"


async def get_ui_hide_greeting(session: AsyncSession, tg_id: int) -> bool:
    raw = await _get_value(session, f"{UI_HIDE_GREETING_PREFIX}{tg_id}")
    return raw == "true"


async def set_ui_hide_greeting(
    session: AsyncSession, tg_id: int, hide: bool
) -> None:
    await _set_value(
        session, f"{UI_HIDE_GREETING_PREFIX}{tg_id}", "true" if hide else "false"
    )


# --- G2/G3: настройки опросов в чате ---

def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


async def get_polls_pin_default(session: AsyncSession) -> bool:
    """G2: дефолт чекбокса «закрепить опрос» при создании из UI."""
    return _parse_bool(
        await _get_value(session, POLLS_PIN_DEFAULT_KEY),
        _POLLS_PIN_DEFAULT_DEFAULT,
    )


async def set_polls_pin_default(session: AsyncSession, value: bool) -> None:
    await _set_value(session, POLLS_PIN_DEFAULT_KEY, "true" if value else "false")


async def get_polls_quorum_auto_close(session: AsyncSession) -> bool:
    """G3: закрывать ли опрос автоматически при достижении N голосов."""
    return _parse_bool(
        await _get_value(session, POLLS_QUORUM_AUTO_CLOSE_KEY),
        _POLLS_QUORUM_AUTO_CLOSE_DEFAULT,
    )


async def set_polls_quorum_auto_close(session: AsyncSession, value: bool) -> None:
    await _set_value(
        session, POLLS_QUORUM_AUTO_CLOSE_KEY, "true" if value else "false"
    )


async def get_polls_live_participants(session: AsyncSession) -> int:
    """G3: сколько живых участников считаем кворумом. Дефолт 5 (шестёрка минус
    автор, который обычно не голосует). Настраивается админом."""
    raw = await _get_value(session, POLLS_LIVE_PARTICIPANTS_KEY)
    try:
        n = int(raw) if raw is not None else _POLLS_LIVE_PARTICIPANTS_DEFAULT
    except ValueError:
        n = _POLLS_LIVE_PARTICIPANTS_DEFAULT
    return max(1, min(20, n))


async def set_polls_live_participants(session: AsyncSession, value: int) -> None:
    v = max(1, min(20, int(value)))
    await _set_value(session, POLLS_LIVE_PARTICIPANTS_KEY, str(v))


async def get_polls_pin_result(session: AsyncSession) -> bool:
    """G3: пинить ли сообщение с оглашением результата (отдельно от пина опроса)."""
    return _parse_bool(
        await _get_value(session, POLLS_PIN_RESULT_KEY),
        _POLLS_PIN_RESULT_DEFAULT,
    )


async def set_polls_pin_result(session: AsyncSession, value: bool) -> None:
    await _set_value(session, POLLS_PIN_RESULT_KEY, "true" if value else "false")
