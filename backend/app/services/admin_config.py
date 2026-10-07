"""Runtime-настройки админа, перекрывающие env-vars.

Все P2-настройки (расписание, генератор фраз, автолох, тик напоминаний,
список фраз лоха) хранятся в таблице admin_config как key/value-строки.
Сложные структуры (например loser_reasons) — JSON-строкой.
"""
from __future__ import annotations

import json

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import AdminConfig

log = structlog.get_logger()

CHUKHAN_WEIGHT_PREFIX = "chukhan_weight:"

# --- Random phrases (P1 уже было + P2 дополнения) ---
RANDOM_PHRASES_ENABLED_KEY = "random_phrases.enabled"
RANDOM_PHRASES_COUNT_KEY = "random_phrases.count"          # legacy: один N
RANDOM_PHRASES_COUNT_MIN_KEY = "random_phrases.count_min"  # A4: диапазон 2..6
RANDOM_PHRASES_COUNT_MAX_KEY = "random_phrases.count_max"
RANDOM_PHRASES_LOOKBACK_DAYS_KEY = "random_phrases.lookback_days"
RANDOM_PHRASES_COLLECTIVE_CHANCE_KEY = "random_phrases.collective_chance"
# P13: «порог + плато» — карантин свежих сообщений при выборе цитат.
RANDOM_PHRASES_RECENCY_HOURS_KEY = "random_phrases.recency_quarantine_hours"
RANDOM_PHRASES_RECENCY_WEIGHT_KEY = "random_phrases.recency_quarantine_weight"
RANDOM_PHRASES_USER_CHANCE_KEY = "random_phrases.user_chance"
# A3: расписание автопостинга
RANDOM_PHRASES_SCHEDULE_MODE_KEY = "random_phrases.schedule_mode"   # daily_n|weekly_n|fixed_times|random_interval
RANDOM_PHRASES_SCHEDULE_PARAM_KEY = "random_phrases.schedule_param"  # JSON: {"n":3} | {"times":["12:00","18:00"]} | {"min_minutes":120}
# GHG6 L: режим сбора фраз. 'words' — N случайных слов; 'phrases' — N целых
# фраз-чанков (по пунктуации); 'mix' — оба пула вместе. До L count_min/count_max
# применялись только к чанкам, поэтому N=2..2 по факту могло выдавать сообщение
# любой длины — баг п.20. Теперь min/max строго ограничивают итоговое
# количество единиц выбранного типа.
RANDOM_PHRASES_MODE_KEY = "random_phrases.mode"
_RANDOM_PHRASES_MODES = ("words", "phrases", "mix")
_RANDOM_PHRASES_MODE_DEFAULT = "mix"

# --- Reminders tick (A2) ---
REMINDERS_TICK_MINUTES_KEY = "reminders.tick_minutes"

# --- Loser reasons CRUD (A1) ---
LOSER_REASONS_KEY = "loser_reasons.list"

# --- Auto-loser (A6) ---
AUTOLOSER_ENABLED_KEY = "autoloser.enabled"
AUTOLOSER_WINDOW_START_HOUR_KEY = "autoloser.window_start_hour"  # default 7
AUTOLOSER_WINDOW_END_HOUR_KEY = "autoloser.window_end_hour"      # default 22
AUTOLOSER_INTERVAL_HOURS_KEY = "autoloser.interval_hours"        # 0 = random раз в сутки
# GHG11: понятный шедулер автолоха вместо «сложного рандома с интервалами».
#   * `autoloser.days` — CSV дней недели (0=пн..6=вс), по умолчанию все;
#   * `autoloser.mode` — "fixed" (одно время) | "random" (раз в сутки) |
#                         "interval" (по слоту день/ночь);
#   * `autoloser.fixed_hour`/`fixed_minute` — время для fixed (18:00);
#   * `autoloser.interval_slot` — "day" | "night" для interval.
AUTOLOSER_DAYS_KEY = "autoloser.days"
AUTOLOSER_MODE_KEY = "autoloser.mode"
AUTOLOSER_FIXED_HOUR_KEY = "autoloser.fixed_hour"
AUTOLOSER_FIXED_MINUTE_KEY = "autoloser.fixed_minute"
AUTOLOSER_INTERVAL_SLOT_KEY = "autoloser.interval_slot"

AUTOLOSER_MODES = ("fixed", "random", "interval")
AUTOLOSER_SLOTS = ("day", "night")
_DEFAULT_AUTOLOSER_DAYS = (0, 1, 2, 3, 4, 5, 6)

# GHG11: раздельные интервалы «день»/«ночь» — общая величина, на которую
# ссылаются другие фичи (интервальный автолох, чухан, рандомные фразы).
INTERVAL_DAY_START_KEY = "intervals.day_start"    # "07:00"
INTERVAL_DAY_END_KEY = "intervals.day_end"        # "23:00"
INTERVAL_NIGHT_START_KEY = "intervals.night_start"  # "23:00"
INTERVAL_NIGHT_END_KEY = "intervals.night_end"      # "07:00"
_DEFAULT_INTERVALS = {
    "day_start": "07:00",
    "day_end": "23:00",
    "night_start": "23:00",
    "night_end": "07:00",
}

# --- T3.4: «магический шар» (/advice / #совет) ---
ADVICE_ENABLED_KEY = "advice.enabled"   # default True
ADVICE_LIST_KEY = "advice.list"

# --- E8: «Червь-пидор» (особая номинация при ролле лоха) ---
WORM_ENABLED_KEY = "worm.enabled"          # default true (механика работает)
WORM_CHANCE_KEY = "worm.chance"            # default 0.01 (1/100)

# Хардкод-дефолты — чтобы можно было выкатить фичу без миграции конфига.
_WORM_ENABLED_DEFAULT = True
_WORM_CHANCE_DEFAULT = 0.01

# --- T3.6: «червь-господин» (носитель звания червя как господин бота) ---
# Тумблеры/проценты режима. Фича-тогл `enabled` default False — выкатываем
# поэтапно, чтобы поведение не включилось до готовности фронта и пулов.
WORM_MASTER_ENABLED_KEY = "worm_master.enabled"            # default False
WORM_MASTER_PUNISH_ENABLED_KEY = "worm_master.punish_enabled"  # default True
WORM_MASTER_YES_ENABLED_KEY = "worm_master.yes_enabled"    # поддакивание, default False
WORM_MASTER_YES_PCT_KEY = "worm_master.yes_pct"            # шанс поддакнуть, default 15
WORM_MASTER_YES_COOLDOWN_MIN_KEY = "worm_master.yes_cooldown_min"  # default 60
# Пулы фраз (JSON-списки, как loser_reasons/advice).
WORM_MASTER_PREFIXES_KEY = "worm_master.prefixes"
WORM_MASTER_SUFFIXES_KEY = "worm_master.suffixes"
WORM_MASTER_AGREES_KEY = "worm_master.agrees"
WORM_MASTER_NAG_KEY = "worm_master.nag"
WORM_PUNISH_KEY = "worm_master.punish"
# T3.6 (в'): отповеди не-господину, дёрнувшему /punish. Раньше брались из
# констант напрямую — правки в админке на них не влияли. Теперь это пулы.
WORM_PUNISH_DENIED_KEY = "worm_master.punish_denied"
WORM_PUNISH_DENIED_NAMED_KEY = "worm_master.punish_denied_named"
WORM_ANNOUNCE_LINES_KEY = "worm_master.announce_lines"

_WORM_MASTER_ENABLED_DEFAULT = False
_WORM_MASTER_PUNISH_ENABLED_DEFAULT = True
_WORM_MASTER_YES_ENABLED_DEFAULT = False
_WORM_MASTER_YES_PCT_DEFAULT = 15
_WORM_MASTER_YES_COOLDOWN_MIN_DEFAULT = 60

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


async def add_chukhan_weight(
    session: AsyncSession, *, tg_id: int, delta: float
) -> float:
    """GHG6 N2: атомарный инкремент веса в admin_config.

    Получаем текущий вес через `get_chukhan_weights` (учитывает env + оверрайды),
    добавляем delta, записываем как новый оверрайд через `set_chukhan_weight`.
    Не позволяем уйти ниже 0 — пользователь может «обнулить» себя только через
    reset, не через отрицательную delta.
    Возвращает новый вес — пригодится для логов / тостов в чат.
    """
    weights = await get_chukhan_weights(session)
    current = weights.get(tg_id, 1.0)
    new = max(0.0, current + delta)
    await set_chukhan_weight(session, tg_id=tg_id, weight=new)
    return new


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

# GHG8 G (03.07): верхний кламп 120→360 мин (п.14 «по-хорошему раз в ~6ч»).
# Реже опрашивать напоминания = меньше SELECT в Neon. Значение задаётся из
# админки; тут только расширен потолок.
_REMINDERS_TICK_MAX = 360


async def get_reminders_tick_minutes(session: AsyncSession) -> int:
    return max(1, min(_REMINDERS_TICK_MAX, await _get_int(session, REMINDERS_TICK_MINUTES_KEY, 10)))


async def set_reminders_tick_minutes(session: AsyncSession, minutes: int) -> None:
    await _set_value(
        session, REMINDERS_TICK_MINUTES_KEY, str(max(1, min(_REMINDERS_TICK_MAX, minutes)))
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


async def get_random_phrases_recency_quarantine_hours(session: AsyncSession) -> float:
    """P13: возраст (часы), младше которого сообщение почти не цитируется.
    0 = карантин выключен (все веса равны). Дефолт 18ч («отстояться сутки»)."""
    return max(0.0, min(168.0, await _get_float(session, RANDOM_PHRASES_RECENCY_HOURS_KEY, 18.0)))


async def set_random_phrases_recency_quarantine_hours(
    session: AsyncSession, hours: float
) -> None:
    await _set_value(
        session, RANDOM_PHRASES_RECENCY_HOURS_KEY, str(max(0.0, min(168.0, hours)))
    )


async def get_random_phrases_recency_quarantine_weight(session: AsyncSession) -> float:
    """P13: вес «свежего» чанка (0..1). 1.0 = веса фактически выключены."""
    return max(0.0, min(1.0, await _get_float(session, RANDOM_PHRASES_RECENCY_WEIGHT_KEY, 0.05)))


async def set_random_phrases_recency_quarantine_weight(
    session: AsyncSession, weight: float
) -> None:
    await _set_value(
        session, RANDOM_PHRASES_RECENCY_WEIGHT_KEY, str(max(0.0, min(1.0, weight)))
    )


async def get_random_phrases_user_chance(session: AsyncSession) -> float:
    """Шанс того, что job вообще выстрелит (1.0 = всегда)."""
    return max(0.0, min(1.0, await _get_float(session, RANDOM_PHRASES_USER_CHANCE_KEY, 1.0)))


async def set_random_phrases_user_chance(session: AsyncSession, chance: float) -> None:
    await _set_value(
        session, RANDOM_PHRASES_USER_CHANCE_KEY, str(max(0.0, min(1.0, chance)))
    )


async def get_random_phrases_mode(session: AsyncSession) -> str:
    """GHG6 L: режим сбора. Невалидное значение → default 'mix'."""
    raw = (await _get_value(session, RANDOM_PHRASES_MODE_KEY)) or _RANDOM_PHRASES_MODE_DEFAULT
    return raw if raw in _RANDOM_PHRASES_MODES else _RANDOM_PHRASES_MODE_DEFAULT


async def set_random_phrases_mode(session: AsyncSession, mode: str) -> None:
    if mode not in _RANDOM_PHRASES_MODES:
        raise ValueError(f"random_phrases.mode must be one of {_RANDOM_PHRASES_MODES}, got {mode!r}")
    await _set_value(session, RANDOM_PHRASES_MODE_KEY, mode)


# GHG-Э19: ГЛОБАЛЬНЫЙ свитчер источника фраз для ВСЕХ пулов сразу (лох, чухан,
# советы, фразы кары и т.д.). Оператор: «не понял, как переключаться между
# ручными и ИИ-фразами — нужен глобальный свитчер». Значения:
#   "both"   — шлём и ручные, и ИИ (дефолт, как было);
#   "manual" — только ручные/импортированные (без ИИ-слопа и персон);
#   "ai"     — только ИИ-фразы (дроп + персоны).
# Применяется в `phrase_meta.effective_pool` — то есть ровно там, где бот ВЫБИРАЕТ
# фразу из пула, и с безопасным фолбэком (если выбранный источник пуст, пул не
# ломается).
PHRASES_SOURCE_MODE_KEY = "phrases.source_mode"
PHRASES_SOURCE_MODES = ("both", "manual", "ai")
_PHRASES_SOURCE_MODE_DEFAULT = "both"


async def get_phrases_source_mode(session: AsyncSession) -> str:
    raw = (await _get_value(session, PHRASES_SOURCE_MODE_KEY)) or _PHRASES_SOURCE_MODE_DEFAULT
    return raw if raw in PHRASES_SOURCE_MODES else _PHRASES_SOURCE_MODE_DEFAULT


async def set_phrases_source_mode(session: AsyncSession, mode: str) -> None:
    if mode not in PHRASES_SOURCE_MODES:
        raise ValueError(
            f"phrases.source_mode must be one of {PHRASES_SOURCE_MODES}, got {mode!r}"
        )
    await _set_value(session, PHRASES_SOURCE_MODE_KEY, mode)


# --- GHG8 P6.3: версия генератора фраз (legacy = нарезка сообщений v1,
# personas = типажи v2). Расписание/шанс/ручной триггер ОБЩИЕ для обеих
# версий (P6.2.b) — переключается только composer.
# GHG11: вариант «типажи» (personas) убран из настроек — остаётся только
# legacy-генератор. Ветка `personas` в `random_phrases` становится недостижимой.
PHRASE_GENERATOR_VERSION_KEY = "phrase_generator.version"
PHRASE_GENERATOR_VERSIONS = ("legacy",)
_PHRASE_GENERATOR_VERSION_DEFAULT = "legacy"


async def get_phrase_generator_version(session: AsyncSession) -> str:
    raw = await _get_value(session, PHRASE_GENERATOR_VERSION_KEY)
    return raw if raw in PHRASE_GENERATOR_VERSIONS else _PHRASE_GENERATOR_VERSION_DEFAULT


async def set_phrase_generator_version(session: AsyncSession, version: str) -> None:
    if version not in PHRASE_GENERATOR_VERSIONS:
        raise ValueError(
            f"phrase_generator.version must be one of {PHRASE_GENERATOR_VERSIONS}, got {version!r}"
        )
    await _set_value(session, PHRASE_GENERATOR_VERSION_KEY, version)


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

def _parse_weekdays(raw: str | None) -> list[int]:
    """"0,1,2" → [0,1,2]. Пусто/мусор → все дни (пн-вс)."""
    if raw is None:
        return list(_DEFAULT_AUTOLOSER_DAYS)
    out: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            d = int(chunk)
        except (ValueError, TypeError):
            continue
        if 0 <= d <= 6 and d not in out:
            out.append(d)
    return sorted(out)


async def get_autoloser_settings(session: AsyncSession) -> dict:
    start_h = max(0, min(23, await _get_int(session, AUTOLOSER_WINDOW_START_HOUR_KEY, 7)))
    end_h = max(0, min(23, await _get_int(session, AUTOLOSER_WINDOW_END_HOUR_KEY, 22)))
    mode = await _get_value(session, AUTOLOSER_MODE_KEY)
    if mode not in AUTOLOSER_MODES:
        # Наследуем из старого поведения: interval_hours>0 → interval, иначе random.
        legacy_interval = await _get_int(session, AUTOLOSER_INTERVAL_HOURS_KEY, 0)
        mode = "interval" if legacy_interval > 0 else "random"
    slot = await _get_value(session, AUTOLOSER_INTERVAL_SLOT_KEY)
    if slot not in AUTOLOSER_SLOTS:
        slot = "day"
    days = _parse_weekdays(await _get_value(session, AUTOLOSER_DAYS_KEY))
    return {
        "enabled": await _get_bool(session, AUTOLOSER_ENABLED_KEY, False),
        "window_start_hour": start_h,
        "window_end_hour": end_h,
        # 0 = random раз в сутки в окне; >0 = фиксированный интервал в часах.
        "interval_hours": max(0, min(72, await _get_int(session, AUTOLOSER_INTERVAL_HOURS_KEY, 0))),
        "days": days,
        "mode": mode,
        "fixed_hour": max(0, min(23, await _get_int(session, AUTOLOSER_FIXED_HOUR_KEY, 18))),
        "fixed_minute": max(0, min(59, await _get_int(session, AUTOLOSER_FIXED_MINUTE_KEY, 0))),
        "interval_slot": slot,
    }


async def set_autoloser_settings(
    session: AsyncSession,
    *,
    enabled: bool,
    window_start_hour: int,
    window_end_hour: int,
    interval_hours: int,
    days: list[int] | None = None,
    mode: str | None = None,
    fixed_hour: int = 18,
    fixed_minute: int = 0,
    interval_slot: str = "day",
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
    if days is not None:
        clean = sorted({d for d in days if 0 <= d <= 6})
        await _set_value(session, AUTOLOSER_DAYS_KEY, ",".join(str(d) for d in clean))
    if mode is not None:
        if mode not in AUTOLOSER_MODES:
            raise ValueError(f"bad autoloser mode: {mode!r}")
        await _set_value(session, AUTOLOSER_MODE_KEY, mode)
    await _set_value(session, AUTOLOSER_FIXED_HOUR_KEY, str(max(0, min(23, fixed_hour))))
    await _set_value(
        session, AUTOLOSER_FIXED_MINUTE_KEY, str(max(0, min(59, fixed_minute)))
    )
    if interval_slot not in AUTOLOSER_SLOTS:
        interval_slot = "day"
    await _set_value(session, AUTOLOSER_INTERVAL_SLOT_KEY, interval_slot)


async def get_intervals(session: AsyncSession) -> dict:
    """GHG11: раздельные интервалы день/ночь ("HH:MM"). Читают разные фичи."""
    return {
        "day_start": await _get_hhmm(session, INTERVAL_DAY_START_KEY, "07:00"),
        "day_end": await _get_hhmm(session, INTERVAL_DAY_END_KEY, "23:00"),
        "night_start": await _get_hhmm(session, INTERVAL_NIGHT_START_KEY, "23:00"),
        "night_end": await _get_hhmm(session, INTERVAL_NIGHT_END_KEY, "07:00"),
    }


async def set_intervals(session: AsyncSession, body: dict) -> None:
    for key, cfg_key, default in (
        ("day_start", INTERVAL_DAY_START_KEY, "07:00"),
        ("day_end", INTERVAL_DAY_END_KEY, "23:00"),
        ("night_start", INTERVAL_NIGHT_START_KEY, "23:00"),
        ("night_end", INTERVAL_NIGHT_END_KEY, "07:00"),
    ):
        if key in body:
            await _set_value(session, cfg_key, _validate_hhmm(body[key], default))


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


# --- GHG11(4): вид ленты активности (новый компактный / старый) ---

FEED_VIEW_COMPACT_KEY = "feed.view_compact"


async def get_feed_view_compact(session: AsyncSession) -> bool:
    """GHG11(4): глобальный переключатель вида ленты.

    Default = True — «новый» компактный вид (миниатюры участников под заданием).
    Оператор: «переключи сразу на новый». Старый вид («спам отдельными блоками»)
    остаётся доступен тумблером в админке.
    """
    return await _get_bool(session, FEED_VIEW_COMPACT_KEY, True)


async def set_feed_view_compact(session: AsyncSession, enabled: bool) -> None:
    await _set_value(
        session, FEED_VIEW_COMPACT_KEY, "true" if enabled else "false"
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
        # GHG8 Q5: ключа нет — отдаём дефолт из кода (6 фраз). Это «6 унылых
        # причин из первого билда», которые видел пользователь: значит его
        # правка в Neon легла НЕ под этот ключ (или не сохранилась).
        log.info("chukhan_reasons.fallback_default", reason="key_missing")
        return list(_DEFAULT_CHUKHAN_REASONS)
    try:
        data = json.loads(raw)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data
        # GHG8 Q5: ключ есть, но не список строк (например объект/число) —
        # тихий фолбэк раньше маскировал это под «6 старых фраз». Логируем.
        log.warning(
            "chukhan_reasons.fallback_default",
            reason="not_list_of_str",
            value_type=type(data).__name__,
        )
    except (ValueError, TypeError) as exc:
        # GHG8 Q5: невалидный JSON в admin_config (ручная правка Neon с косяком,
        # напр. лишняя/недостающая запятая) → фолбэк на дефолт. Это и есть
        # корень жалобы п.5: правка не применялась, а ошибка глоталась молча.
        log.warning(
            "chukhan_reasons.fallback_default",
            reason="invalid_json",
            error=str(exc),
            raw_len=len(raw),
        )
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


# --- H.3: таймер оспаривания чухана (прод-фидбек 22.06 #1) ---
# Сразу после анонса чухана бот публикует опрос-обжалование. Раньше `open_period`
# был захардкожен (3600с = 1ч) — «никто не успел толком проголосовать». Теперь
# длительность настраивается из чухан-подменю, дефолт поднят до 6 часов.

CHUKHAN_APPEAL_POLL_MINUTES_KEY = "chukhan.appeal_poll_minutes"
_CHUKHAN_APPEAL_POLL_MINUTES_DEFAULT = 360
CHUKHAN_APPEAL_POLL_MINUTES_BOUNDS: tuple[int, int] = (15, 1440)


def clamp_appeal_poll_minutes(minutes: int) -> int:
    """Ограничить длительность опроса-обжалования (15 мин … 24 ч).

    Нечисловое/мусорное значение → дефолт (тот же приём, что у
    `media_reactions.clamp_wait_window`)."""
    lo, hi = CHUKHAN_APPEAL_POLL_MINUTES_BOUNDS
    try:
        v = int(minutes)
    except (TypeError, ValueError):
        return _CHUKHAN_APPEAL_POLL_MINUTES_DEFAULT
    return max(lo, min(hi, v))


async def get_chukhan_appeal_poll_minutes(session: AsyncSession) -> int:
    return clamp_appeal_poll_minutes(
        await _get_int(
            session,
            CHUKHAN_APPEAL_POLL_MINUTES_KEY,
            _CHUKHAN_APPEAL_POLL_MINUTES_DEFAULT,
        )
    )


async def set_chukhan_appeal_poll_minutes(
    session: AsyncSession, minutes: int
) -> None:
    await _set_value(
        session,
        CHUKHAN_APPEAL_POLL_MINUTES_KEY,
        str(clamp_appeal_poll_minutes(minutes)),
    )


# --- T3.4: advice («магический шар») ---

async def get_advice_enabled(session: AsyncSession) -> bool:
    return await _get_bool(session, ADVICE_ENABLED_KEY, True)


async def set_advice_enabled(session: AsyncSession, enabled: bool) -> None:
    await _set_value(session, ADVICE_ENABLED_KEY, "true" if enabled else "false")


async def get_advice_phrases(session: AsyncSession) -> list[str]:
    """Кастомный пул советов или дефолт из app.services.advice.

    Дефолт НЕ пишем в БД при чтении — новые фразы из кода подхватятся, пока
    пользователь не начал кастомизацию (как loser_reasons)."""
    from app.services.advice import DEFAULT_ADVICE_PHRASES

    raw = await _get_value(session, ADVICE_LIST_KEY)
    if raw is None:
        return list(DEFAULT_ADVICE_PHRASES)
    try:
        data = json.loads(raw)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data
    except (ValueError, TypeError):
        pass
    return list(DEFAULT_ADVICE_PHRASES)


async def set_advice_phrases(session: AsyncSession, phrases: list[str]) -> None:
    seen: set[str] = set()
    cleaned: list[str] = []
    for p in phrases:
        p = p.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        cleaned.append(p)
    await _set_value(session, ADVICE_LIST_KEY, json.dumps(cleaned, ensure_ascii=False))


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

# GHG8 P3: иммунитет именинника к лоху/чухану.
#  - "announce" — именинник может выпасть в рулетке, но вместо записи идёт
#    оглашение «мог бы стать %name%, но у него ДР» + реролл (default).
#  - "silent"   — именинник исключается из выборки молча.
# Режима «off» нет by design (GHG7.txt стр. 47): иммунитет в ДР есть всегда,
# настраивается только подача.
BIRTHDAYS_IMMUNITY_MODE_KEY = "birthdays.immunity_mode"
IMMUNITY_MODES = ("announce", "silent")
IMMUNITY_MODE_DEFAULT = "announce"


async def get_birthdays_immunity_mode(session: AsyncSession) -> str:
    raw = await _get_value(session, BIRTHDAYS_IMMUNITY_MODE_KEY)
    return raw if raw in IMMUNITY_MODES else IMMUNITY_MODE_DEFAULT


async def set_birthdays_immunity_mode(session: AsyncSession, mode: str) -> None:
    if mode not in IMMUNITY_MODES:
        raise ValueError(f"invalid immunity mode: {mode!r}")
    await _set_value(session, BIRTHDAYS_IMMUNITY_MODE_KEY, mode)

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
            # GHG11: понятный шедулер автолоха.
            "days": auto["days"],
            "mode": auto["mode"],
            "fixed_hour": auto["fixed_hour"],
            "fixed_minute": auto["fixed_minute"],
            "interval_slot": auto["interval_slot"],
        },
        "intervals": await get_intervals(session),
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
            # GHG8 P3: режим иммунитета именинника (announce|silent).
            "immunity_mode": await get_birthdays_immunity_mode(session),
        },
        "chukhan": {
            "weekday": max(0, min(6, await _get_int(session, CHUKHAN_WEEKDAY_KEY, 0))),
            "window_start": await _get_hhmm(session, CHUKHAN_WINDOW_START_KEY, "07:30"),
            "window_end": await _get_hhmm(session, CHUKHAN_WINDOW_END_KEY, "12:00"),
        },
        # GHG8 P7: «мёртвый чат». Ключ живёт в services/dead_chat.py, здесь —
        # только проводка в агрегат master-toggles (job сам читает enabled).
        "dead_chat": {
            "enabled": await _get_bool(session, "dead_chat.enabled", True),
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
            days=loser.get("days") if "days" in loser else None,
            mode=loser.get("mode"),
            fixed_hour=int(loser.get("fixed_hour", 18)),
            fixed_minute=int(loser.get("fixed_minute", 0)),
            interval_slot=loser.get("interval_slot", "day"),
        )
        await _set_value(session, LOSER_AUTO_PER_DAY_KEY, str(max(1, min(12, per_day))))

    intervals = body.get("intervals") or {}
    if intervals:
        await set_intervals(session, intervals)

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
    if "immunity_mode" in birthdays:
        mode = birthdays["immunity_mode"]
        if mode in IMMUNITY_MODES:
            await _set_value(session, BIRTHDAYS_IMMUNITY_MODE_KEY, mode)

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

    # GHG8 P7: master-toggle «мёртвого чата».
    dead_chat = body.get("dead_chat") or {}
    if "enabled" in dead_chat:
        await _set_value(
            session,
            "dead_chat.enabled",
            "true" if dead_chat["enabled"] else "false",
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


# --- T3.6: «червь-господин» ---

def _dedup_clean(phrases: list[str]) -> list[str]:
    """strip + дроп пустых + дедуп с сохранением порядка (как set_*_reasons)."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for p in phrases:
        p = p.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        cleaned.append(p)
    return cleaned


async def _get_pool(session: AsyncSession, key: str, default: list[str]) -> list[str]:
    """Кастомный JSON-пул или дефолт из кода (дефолт НЕ пишем в БД при чтении —
    новые фразы из кода подхватятся, пока админ не начал кастомизацию)."""
    raw = await _get_value(session, key)
    if raw is None:
        return list(default)
    try:
        data = json.loads(raw)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data
    except (ValueError, TypeError):
        pass
    return list(default)


async def _set_pool(
    session: AsyncSession, key: str, phrases: list[str], use_counts_key: str | None = None
) -> None:
    cleaned = _dedup_clean(phrases)
    await _set_value(session, key, json.dumps(cleaned, ensure_ascii=False))
    if use_counts_key is not None:
        from app.services.phrase_weights import cleanup_use_counts

        await cleanup_use_counts(session, use_counts_key, cleaned)


# Тумблеры/проценты.
async def is_worm_master_enabled(session: AsyncSession) -> bool:
    return await _get_bool(session, WORM_MASTER_ENABLED_KEY, _WORM_MASTER_ENABLED_DEFAULT)


async def set_worm_master_enabled(session: AsyncSession, enabled: bool) -> None:
    await _set_value(session, WORM_MASTER_ENABLED_KEY, "true" if enabled else "false")


# Э19: единоразовый флаг «инфо-уведомление о передаче червя отправлено». Живёт в
# `admin_config`, чтобы после деплоя объявить фичу ровно один раз и пережить
# рестарт контейнера (in-memory флаг бы сбросился и спамил при каждом перезапуске).
_WORM_TRANSFER_ANNOUNCED_KEY = "game.worm_transfer.announced"


async def get_worm_transfer_announced(session: AsyncSession) -> bool:
    return await _get_bool(session, _WORM_TRANSFER_ANNOUNCED_KEY, False)


async def set_worm_transfer_announced(session: AsyncSession, value: bool) -> None:
    await _set_value(session, _WORM_TRANSFER_ANNOUNCED_KEY, "true" if value else "false")


async def is_worm_master_punish_enabled(session: AsyncSession) -> bool:
    return await _get_bool(
        session, WORM_MASTER_PUNISH_ENABLED_KEY, _WORM_MASTER_PUNISH_ENABLED_DEFAULT
    )


async def set_worm_master_punish_enabled(session: AsyncSession, enabled: bool) -> None:
    await _set_value(session, WORM_MASTER_PUNISH_ENABLED_KEY, "true" if enabled else "false")


async def is_worm_master_yes_enabled(session: AsyncSession) -> bool:
    return await _get_bool(
        session, WORM_MASTER_YES_ENABLED_KEY, _WORM_MASTER_YES_ENABLED_DEFAULT
    )


async def set_worm_master_yes_enabled(session: AsyncSession, enabled: bool) -> None:
    await _set_value(session, WORM_MASTER_YES_ENABLED_KEY, "true" if enabled else "false")


async def get_worm_master_yes_pct(session: AsyncSession) -> int:
    v = await _get_int(session, WORM_MASTER_YES_PCT_KEY, _WORM_MASTER_YES_PCT_DEFAULT)
    return max(0, min(100, v))


async def set_worm_master_yes_pct(session: AsyncSession, pct: int) -> None:
    await _set_value(session, WORM_MASTER_YES_PCT_KEY, str(max(0, min(100, int(pct)))))


async def get_worm_master_yes_cooldown_min(session: AsyncSession) -> int:
    v = await _get_int(
        session, WORM_MASTER_YES_COOLDOWN_MIN_KEY, _WORM_MASTER_YES_COOLDOWN_MIN_DEFAULT
    )
    return max(0, min(1440, v))


async def set_worm_master_yes_cooldown_min(session: AsyncSession, minutes: int) -> None:
    await _set_value(
        session, WORM_MASTER_YES_COOLDOWN_MIN_KEY, str(max(0, min(1440, int(minutes))))
    )


# Пулы фраз. use_counts ведём для всех, кроме nag и announce (одноразовые/честный
# random — см. worm_master.py).
async def get_worm_master_prefixes(session: AsyncSession) -> list[str]:
    from app.services.worm_master import DEFAULT_WORM_MASTER_PREFIXES

    return await _get_pool(session, WORM_MASTER_PREFIXES_KEY, DEFAULT_WORM_MASTER_PREFIXES)


async def set_worm_master_prefixes(session: AsyncSession, phrases: list[str]) -> None:
    from app.services.phrase_weights import WORM_MASTER_PREFIX_USE_COUNTS_KEY

    await _set_pool(session, WORM_MASTER_PREFIXES_KEY, phrases, WORM_MASTER_PREFIX_USE_COUNTS_KEY)


async def get_worm_master_suffixes(session: AsyncSession) -> list[str]:
    from app.services.worm_master import DEFAULT_WORM_MASTER_SUFFIXES

    return await _get_pool(session, WORM_MASTER_SUFFIXES_KEY, DEFAULT_WORM_MASTER_SUFFIXES)


async def set_worm_master_suffixes(session: AsyncSession, phrases: list[str]) -> None:
    from app.services.phrase_weights import WORM_MASTER_SUFFIX_USE_COUNTS_KEY

    await _set_pool(session, WORM_MASTER_SUFFIXES_KEY, phrases, WORM_MASTER_SUFFIX_USE_COUNTS_KEY)


async def get_worm_master_agrees(session: AsyncSession) -> list[str]:
    from app.services.worm_master import DEFAULT_WORM_MASTER_AGREES

    return await _get_pool(session, WORM_MASTER_AGREES_KEY, DEFAULT_WORM_MASTER_AGREES)


async def set_worm_master_agrees(session: AsyncSession, phrases: list[str]) -> None:
    from app.services.phrase_weights import WORM_MASTER_AGREE_USE_COUNTS_KEY

    await _set_pool(session, WORM_MASTER_AGREES_KEY, phrases, WORM_MASTER_AGREE_USE_COUNTS_KEY)


async def get_worm_master_nag(session: AsyncSession) -> list[str]:
    from app.services.worm_master import DEFAULT_WORM_MASTER_NAG

    return await _get_pool(session, WORM_MASTER_NAG_KEY, DEFAULT_WORM_MASTER_NAG)


async def set_worm_master_nag(session: AsyncSession, phrases: list[str]) -> None:
    await _set_pool(session, WORM_MASTER_NAG_KEY, phrases)


async def get_worm_punish(session: AsyncSession) -> list[str]:
    from app.services.worm_master import DEFAULT_WORM_PUNISH_PHRASES

    return await _get_pool(session, WORM_PUNISH_KEY, DEFAULT_WORM_PUNISH_PHRASES)


async def get_worm_punish_denied(session: AsyncSession) -> list[str]:
    from app.services.worm_master import DEFAULT_WORM_PUNISH_DENIED

    return await _get_pool(session, WORM_PUNISH_DENIED_KEY, DEFAULT_WORM_PUNISH_DENIED)


async def set_worm_punish_denied(session: AsyncSession, phrases: list[str]) -> None:
    await _set_pool(session, WORM_PUNISH_DENIED_KEY, phrases)


async def get_worm_punish_denied_named(session: AsyncSession) -> list[str]:
    from app.services.worm_master import DEFAULT_WORM_PUNISH_DENIED_NAMED

    return await _get_pool(
        session, WORM_PUNISH_DENIED_NAMED_KEY, DEFAULT_WORM_PUNISH_DENIED_NAMED
    )


async def set_worm_punish_denied_named(
    session: AsyncSession, phrases: list[str]
) -> None:
    await _set_pool(session, WORM_PUNISH_DENIED_NAMED_KEY, phrases)


async def set_worm_punish(session: AsyncSession, phrases: list[str]) -> None:
    from app.services.phrase_weights import WORM_PUNISH_USE_COUNTS_KEY

    await _set_pool(session, WORM_PUNISH_KEY, phrases, WORM_PUNISH_USE_COUNTS_KEY)


async def get_worm_announce_lines(session: AsyncSession) -> list[str]:
    from app.services.worm_master import DEFAULT_WORM_ANNOUNCE_LINES

    return await _get_pool(session, WORM_ANNOUNCE_LINES_KEY, DEFAULT_WORM_ANNOUNCE_LINES)


async def set_worm_announce_lines(session: AsyncSession, phrases: list[str]) -> None:
    await _set_pool(session, WORM_ANNOUNCE_LINES_KEY, phrases)


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
# H.1 (фидбек 19.06 #3): ОТДЕЛЬНЫЙ пул коротких реплик для ответа на reply/mention.
# JSON-список, как loser_reasons/advice (дефолт в code не пишется в БД до правки).
BOT_REACT_REPLY_PHRASES_KEY = "bot_reactions.reply_phrases"


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


# H.1: пул коротких реплик бота (reply/mention). use_counts ведём — чередуем, чтобы
# одна и та же фраза подряд не повторялась.
async def get_reply_phrases(session: AsyncSession) -> list[str]:
    from app.services.random_phrases import DEFAULT_REPLY_PHRASES

    return await _get_pool(session, BOT_REACT_REPLY_PHRASES_KEY, list(DEFAULT_REPLY_PHRASES))


async def set_reply_phrases(session: AsyncSession, phrases: list[str]) -> None:
    from app.services.phrase_weights import REPLY_USE_COUNTS_KEY

    await _set_pool(session, BOT_REACT_REPLY_PHRASES_KEY, phrases, REPLY_USE_COUNTS_KEY)


# --- GHG7 P5: реакции бота на медиа (мемы/подборки) ---
# Пулы фраз и whitelist эмодзи — JSON-списки (паттерн loser_reasons, дефолты в
# app/services/media_reactions.py, не пишутся в БД до первой правки админом).
MEDIA_SINGLE_PHRASES_KEY = "media_reactions.single_phrases"
MEDIA_COLLECTION_PHRASES_KEY = "media_reactions.collection_phrases"
MEDIA_EMOJI_WHITELIST_KEY = "media_reactions.emoji_whitelist"
# GHG8 Q7.b: persist «последнего медиа» для force-кнопок — переживает рестарт
# Space (in-memory `_recent` хендлера обнуляется). Один ключ на весь бот, JSON:
# {str(chat_id): {"kind": "single"|"collection", "message_id": int,
#  "author_name": str}}. Пишется best-effort при каждом новом медиа (одна
# UPSERT-строка, нагрузка на Neon сопоставима с chat_capture).
MEDIA_RECENT_MEDIA_KEY = "media_reactions.recent_media"

# Поведение (см. handlers/media_reactions.py — один честный ролл на мем).
# mode: always|chance|wait_then_chance|never.
# single_response_mode: emoji|phrase|both|random_one (что слать на одиночный мем).
MEDIA_ENABLED_KEY = "media_reactions.enabled"                      # master, default true
MEDIA_SINGLE_ENABLED_KEY = "media_reactions.single_enabled"        # default true
MEDIA_COLLECTION_ENABLED_KEY = "media_reactions.collection_enabled"  # default true
MEDIA_MODE_KEY = "media_reactions.mode"                            # default wait_then_chance
# Единый честный шанс среагировать на мем (раньше было base/max для серии тиков,
# что копилось до ~98%). Старые ключи base/max больше не читаются.
MEDIA_CHANCE_PCT_KEY = "media_reactions.chance_pct"                # default 30
# Грейс-окно (мин) для wait_then_chance: ждать перед роллом, давая людям время.
MEDIA_WAIT_WINDOW_MIN_KEY = "media_reactions.wait_window_min"      # default 15
MEDIA_SINGLE_RESPONSE_MODE_KEY = "media_reactions.single_response_mode"  # default random_one

_MEDIA_VALID_MODES = ("always", "chance", "wait_then_chance", "never")
_MEDIA_VALID_SINGLE_MODES = ("emoji", "phrase", "both", "random_one")


async def get_media_reactions_settings(session: AsyncSession) -> dict:
    """Агрегат поведения медиа-реакций для UI (без пулов фраз — те отдельно)."""
    mode = await _get_value(session, MEDIA_MODE_KEY) or "wait_then_chance"
    if mode not in _MEDIA_VALID_MODES:
        mode = "wait_then_chance"
    single_mode = await _get_value(session, MEDIA_SINGLE_RESPONSE_MODE_KEY) or "random_one"
    if single_mode not in _MEDIA_VALID_SINGLE_MODES:
        single_mode = "random_one"
    from app.services.media_reactions import clamp_wait_window

    return {
        "enabled": await _get_bool(session, MEDIA_ENABLED_KEY, True),
        "single_enabled": await _get_bool(session, MEDIA_SINGLE_ENABLED_KEY, True),
        "collection_enabled": await _get_bool(session, MEDIA_COLLECTION_ENABLED_KEY, True),
        "mode": mode,
        "chance_pct": max(0, min(100, await _get_int(session, MEDIA_CHANCE_PCT_KEY, 30))),
        "wait_window_min": clamp_wait_window(
            await _get_int(session, MEDIA_WAIT_WINDOW_MIN_KEY, 15)
        ),
        "single_response_mode": single_mode,
    }


async def set_media_reactions_settings(
    session: AsyncSession,
    *,
    enabled: bool | None = None,
    single_enabled: bool | None = None,
    collection_enabled: bool | None = None,
    mode: str | None = None,
    chance_pct: int | None = None,
    wait_window_min: int | None = None,
    single_response_mode: str | None = None,
) -> None:
    if enabled is not None:
        await _set_value(session, MEDIA_ENABLED_KEY, "true" if enabled else "false")
    if single_enabled is not None:
        await _set_value(session, MEDIA_SINGLE_ENABLED_KEY, "true" if single_enabled else "false")
    if collection_enabled is not None:
        await _set_value(
            session, MEDIA_COLLECTION_ENABLED_KEY, "true" if collection_enabled else "false"
        )
    if mode is not None and mode in _MEDIA_VALID_MODES:
        await _set_value(session, MEDIA_MODE_KEY, mode)
    if chance_pct is not None:
        await _set_value(session, MEDIA_CHANCE_PCT_KEY, str(max(0, min(100, chance_pct))))
    if wait_window_min is not None:
        from app.services.media_reactions import clamp_wait_window

        await _set_value(
            session, MEDIA_WAIT_WINDOW_MIN_KEY, str(clamp_wait_window(wait_window_min))
        )
    if single_response_mode is not None and single_response_mode in _MEDIA_VALID_SINGLE_MODES:
        await _set_value(session, MEDIA_SINGLE_RESPONSE_MODE_KEY, single_response_mode)


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


# GHG8 P4.1.b: формат отображения юзера в welcome-блоках. Один селектор на
# ВСЕ блоки (чухан/гл.лох/лох дня/червь) — решение из GHG7.txt стр. 27.
# Per-user (как hide_greeting): каждый настраивает себе сам.
UI_WELCOME_FORMAT_PREFIX = "ui.welcome_format:"
WELCOME_FORMATS = ("name", "avatar", "both")
_WELCOME_FORMAT_DEFAULT = "avatar"


async def get_ui_welcome_format(session: AsyncSession, tg_id: int) -> str:
    raw = await _get_value(session, f"{UI_WELCOME_FORMAT_PREFIX}{tg_id}")
    return raw if raw in WELCOME_FORMATS else _WELCOME_FORMAT_DEFAULT


async def set_ui_welcome_format(
    session: AsyncSession, tg_id: int, fmt: str
) -> None:
    if fmt not in WELCOME_FORMATS:
        fmt = _WELCOME_FORMAT_DEFAULT
    await _set_value(session, f"{UI_WELCOME_FORMAT_PREFIX}{tg_id}", fmt)


# GHG11(7): «не показывать события участника в моей ленте». Храним СПИСОК
# внутренних id через запятую: `ui.muted_feed:{tg_id}` -> "3,5". Фильтр
# персональный (каждый настраивает себе сам), а собственные события участника
# замьютить нельзя — сервер всегда оставляет записи смотрящего (см. feed).
UI_MUTED_FEED_PREFIX = "ui.muted_feed:"


async def get_ui_muted_feed(session: AsyncSession, tg_id: int) -> set[int]:
    """Кого текущий юзер скрыл из своей ленты (внутренние id)."""
    raw = await _get_value(session, f"{UI_MUTED_FEED_PREFIX}{tg_id}")
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return out


async def set_ui_muted_feed(
    session: AsyncSession, tg_id: int, user_ids: set[int] | list[int]
) -> None:
    clean = sorted({int(i) for i in user_ids})
    await _set_value(
        session, f"{UI_MUTED_FEED_PREFIX}{tg_id}", ",".join(str(i) for i in clean)
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


# =============================================================================
# GHG6 N2: пост-фактум 5★ опрос «как собрались» + штраф +0.5 за пропуск
# =============================================================================
#
# `meeting_feedback.enabled` — master-toggle scheduler-job'а JOB_MEETING_FEEDBACK.
#   По умолчанию false (фича для опытных групп — не каждый чат хочет «оценивать
#   встречу» автопостом). Админ включает в UI.
# `meeting_feedback.notify_absence` — отдельный toggle: писать ли в чат тост
#   «@user пропустил встречу — +0.5 к весу чухана». Дефолт true: смысл фичи
#   именно в публичности; админ может выключить если оно создаёт токсичную
#   атмосферу.
# `meeting_feedback.absence_weight_delta` — насколько поднимать вес чухана.
#   Дефолт +0.5 как в исходной формулировке п.18.

MEETING_FEEDBACK_ENABLED_KEY = "meeting_feedback.enabled"
MEETING_FEEDBACK_NOTIFY_ABSENCE_KEY = "meeting_feedback.notify_absence"
MEETING_FEEDBACK_ABSENCE_WEIGHT_KEY = "meeting_feedback.absence_weight_delta"

_MEETING_FEEDBACK_ENABLED_DEFAULT = False
_MEETING_FEEDBACK_NOTIFY_DEFAULT = True
_MEETING_FEEDBACK_WEIGHT_DEFAULT = 0.5


async def get_meeting_feedback_enabled(session: AsyncSession) -> bool:
    return _parse_bool(
        await _get_value(session, MEETING_FEEDBACK_ENABLED_KEY),
        _MEETING_FEEDBACK_ENABLED_DEFAULT,
    )


async def set_meeting_feedback_enabled(session: AsyncSession, value: bool) -> None:
    await _set_value(
        session, MEETING_FEEDBACK_ENABLED_KEY, "true" if value else "false"
    )


async def get_meeting_feedback_notify_absence(session: AsyncSession) -> bool:
    return _parse_bool(
        await _get_value(session, MEETING_FEEDBACK_NOTIFY_ABSENCE_KEY),
        _MEETING_FEEDBACK_NOTIFY_DEFAULT,
    )


async def set_meeting_feedback_notify_absence(
    session: AsyncSession, value: bool
) -> None:
    await _set_value(
        session, MEETING_FEEDBACK_NOTIFY_ABSENCE_KEY, "true" if value else "false"
    )


async def get_meeting_feedback_absence_weight(session: AsyncSession) -> float:
    """Сколько поднимать вес чухана при was_absent=True. Default +0.5."""
    raw = await _get_value(session, MEETING_FEEDBACK_ABSENCE_WEIGHT_KEY)
    if raw is None:
        return _MEETING_FEEDBACK_WEIGHT_DEFAULT
    try:
        return max(0.0, float(raw))
    except (ValueError, TypeError):
        return _MEETING_FEEDBACK_WEIGHT_DEFAULT


async def set_meeting_feedback_absence_weight(
    session: AsyncSession, value: float
) -> None:
    await _set_value(
        session, MEETING_FEEDBACK_ABSENCE_WEIGHT_KEY, str(max(0.0, value))
    )


# --- GHG10: игровая подсистема (опыт/уровни/ранги/ачивки) ---
# Рубильник и отладочное исключение живут здесь (конфиг — наше всё),
# а семантика игровой системы — в `app/services/game/`.
GAME_ENABLED_KEY = "game.enabled"
# TG-id через запятую — кому гейтинг по рангам не указ («Серж нео»).
GAME_DEBUG_TG_IDS_KEY = "game.debug_tg_ids"

# Default: включено. Изначально закладывалось `False` (поэтапная выкатка, как
# `worm_master.enabled`), но UI-рубильника в админке пока НЕТ (Э5.5), а изменения
# уже задеплоены — поэтому дефолт поднят в `True`, чтобы игровая система была
# видна в мини-аппе. Выключается установкой ключа `game.enabled=false` в
# `admin_config` (вернуть строгий дефолт — снова `False`, когда появится UI).
_GAME_ENABLED_DEFAULT = True


def _parse_tg_id_list(raw: str | None) -> list[int]:
    """"1, 2,3" → [1, 2, 3]. Мусор молча игнорируем."""
    if not raw:
        return []
    out: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except (ValueError, TypeError):
            log.warning("admin_config.bad_tg_id_in_list", value=chunk)
    return out


async def get_game_enabled(session: AsyncSession) -> bool:
    """Главный рубильник GHG10. Выключен по умолчанию."""
    return await _get_bool(session, GAME_ENABLED_KEY, _GAME_ENABLED_DEFAULT)


async def set_game_enabled(session: AsyncSession, value: bool) -> None:
    await _set_value(session, GAME_ENABLED_KEY, "true" if value else "false")


async def get_game_debug_tg_ids(session: AsyncSession) -> list[int]:
    """Кому ранг-гейтинг не указ (отладка всех функций)."""
    return _parse_tg_id_list(await _get_value(session, GAME_DEBUG_TG_IDS_KEY))


async def set_game_debug_tg_ids(session: AsyncSession, ids: list[int]) -> None:
    await _set_value(
        session, GAME_DEBUG_TG_IDS_KEY, ",".join(str(i) for i in ids)
    )


# --- GHG10 Э13: сводка, поминовения, случайные события, контрабанда ---
# Четыре «социальные» фичи живут на одних и тех же дефолтах из
# `services/game/config.py` — числа не дублируем, берём оттуда.
GAME_DIGEST_ENABLED_KEY = "game.digest.enabled"
GAME_DIGEST_INTERVAL_KEY = "game.digest.interval_hours"
GAME_DIGEST_LAST_FLUSH_KEY = "game.digest.last_flush_at"

GAME_MEMORIAL_ENABLED_KEY = "game.memorial.enabled"
GAME_MEMORIAL_SILENCE_KEY = "game.memorial.silence_days"
GAME_MEMORIAL_REPEAT_KEY = "game.memorial.repeat_days"

GAME_EVENTS_ENABLED_KEY = "game.events.enabled"
GAME_EVENTS_CHANCE_KEY = "game.events.chance_percent"
GAME_EVENTS_MAX_PER_DAY_KEY = "game.events.max_per_day"
GAME_EVENTS_MIN_PER_DAY_KEY = "game.events.min_per_day"
GAME_EVENTS_MIN_GAP_KEY = "game.events.min_gap_hours"
# Дневное окно публикации событий (локальное время чата, UTC+3).
GAME_EVENTS_DAY_START_KEY = "game.events.day_start_hour"
GAME_EVENTS_DAY_END_KEY = "game.events.day_end_hour"

# Э18: единый режим «активностей» для ВСЕХ авто-постов (живые часы + «не
# перебивать флуд»). См. `services/game/activity.py`.
GAME_ACTIVITY_DAY_START_KEY = "game.activity.day_start_hour"
GAME_ACTIVITY_DAY_END_KEY = "game.activity.day_end_hour"
GAME_ACTIVITY_QUIET_KEY = "game.activity.quiet_minutes"
# Единый бюджет дня: максимум авто-постов бота за локальные сутки (0 — без лимита).
GAME_ACTIVITY_MAX_POSTS_KEY = "game.activity.max_posts_per_day"

# Э19: буфер ачивок («тихо копим → сводка») vs мгновенный постинг (как раньше).
GAME_ACHIEVEMENTS_POST_MODE_KEY = "game.achievements.post_mode"
GAME_ACHIEVEMENTS_POOL_INTERVAL_KEY = "game.achievements.pool.interval_hours"
GAME_ACHIEVEMENTS_POOL_MORNING_KEY = "game.achievements.pool.morning_hour"
GAME_ACHIEVEMENTS_POOL_MIN_ITEMS_KEY = "game.achievements.pool.min_items"
GAME_ACHIEVEMENTS_POOL_GAP_KEY = "game.achievements.pool.gap_minutes"
GAME_ACHIEVEMENTS_POOL_LAST_FLUSH_KEY = "game.achievements.pool.last_flush_at"

# Э20: режим вывода бота в основной чат (normal / achievements / all). См.
# `game.config.CHAT_OUTPUT_MODE`. Без миграции — обычный ключ admin_config.
GAME_CHAT_OUTPUT_MODE_KEY = "game.chat.output_mode"

GAME_CONTRABAND_ENABLED_KEY = "game.contraband.enabled"
GAME_CONTRABAND_CHANCE_KEY = "game.contraband.chance_percent"
GAME_CONTRABAND_CAP_KEY = "game.contraband.daily_cap"
GAME_CONTRABAND_WORDS_KEY = "game.contraband.words"

# Э14: голосовые задания.
GAME_VOICE_ENABLED_KEY = "game.voice.enabled"
GAME_VOICE_POLL_KEY = "game.voice.poll_enabled"
GAME_VOICE_MIN_GAP_KEY = "game.voice.min_gap_hours"
GAME_VOICE_ALT_MODE_KEY = "game.voice.alt_mode_enabled"

# Э15: музыкальная предложка (GHG8 H.7).
GAME_MUSIC_ENABLED_KEY = "game.music.enabled"
GAME_MUSIC_WEEKDAY_KEY = "game.music.weekday"
GAME_MUSIC_HOUR_KEY = "game.music.hour"
GAME_MUSIC_ATTRIBUTE_KEY = "game.music.attribute"

# Э16 (H.8): мьюзик-гейм «угадай, кто предложил трек» — авто-вызов (опция).
GAME_MUSIC_GAME_ENABLED_KEY = "game.music.game_enabled"
GAME_MUSIC_GAME_WEEKDAY_KEY = "game.music.game_weekday"
GAME_MUSIC_GAME_HOUR_KEY = "game.music.game_hour"

# Как и у рубильника игры: фичи, которые пишут в чат, по умолчанию включены,
# а режим сводки — ВЫКЛЮЧЕН (задание: «пока этот режим неактивен, я хочу
# понаблюдать за поведением бота»). Переключается ключом.
_GAME_DIGEST_ENABLED_DEFAULT = False
_GAME_MEMORIAL_ENABLED_DEFAULT = True
_GAME_EVENTS_ENABLED_DEFAULT = True
_GAME_CONTRABAND_ENABLED_DEFAULT = True
# Задания выходят в чат сами — как и события, по умолчанию включены; голосование
# за лучший вариант — ВЫКЛЮЧЕНО (по заданию «по умолчанию голосование выкл»).
_GAME_VOICE_ENABLED_DEFAULT = True
_GAME_VOICE_POLL_DEFAULT = False
# Э19+: альтернативный режим награды (с шансом 50/50 — «только первому»).
# По умолчанию ВЫКЛ: задание остаётся «участвуют все до закрытия», как раньше.
_GAME_VOICE_ALT_MODE_DEFAULT = False
# Музыкальная предложка — фича из старого backlog (P3, «дизайн не согласован»),
# поэтому по умолчанию ВЫКЛЮЧЕНА: включит оператор, когда решит запустить.
_GAME_MUSIC_ENABLED_DEFAULT = False
_GAME_MUSIC_ATTRIBUTE_DEFAULT = True
# Мьюзик-гейм — тоже опция: авто-вызов по умолчанию ВЫКЛ (задание H.8).
_GAME_MUSIC_GAME_ENABLED_DEFAULT = False


def _game_defaults() -> dict:
    """Дефолты из единственной точки тюнинга (ленивый импорт — цикл модулей)."""
    from app.services.game import config as game_config

    return {
        "digest_interval": game_config.DIGEST_DEFAULT_INTERVAL,
        "memorial_silence_days": game_config.MEMORIAL_SILENCE_DAYS,
        "memorial_repeat_days": game_config.MEMORIAL_REPEAT_DAYS,
        "events_chance_percent": game_config.EVENTS_CHANCE_PERCENT,
        "events_max_per_day": game_config.EVENTS_MAX_PER_DAY,
        "events_min_per_day": game_config.EVENTS_MIN_PER_DAY,
        "events_min_gap_hours": game_config.EVENTS_MIN_GAP_HOURS,
        "events_day_start_hour": game_config.EVENTS_DAY_START_HOUR,
        "events_day_end_hour": game_config.EVENTS_DAY_END_HOUR,
        "activity_day_start_hour": game_config.ACTIVITY_DAY_START_HOUR,
        "activity_day_end_hour": game_config.ACTIVITY_DAY_END_HOUR,
        "activity_quiet_minutes": game_config.ACTIVITY_QUIET_MINUTES,
        "activity_max_posts_per_day": game_config.ACTIVITY_MAX_POSTS_PER_DAY,
        "achievements_pool_interval": game_config.ACHIEVEMENTS_POOL_DEFAULT_INTERVAL,
        "achievements_pool_morning_hour": game_config.ACHIEVEMENTS_POOL_MORNING_HOUR,
        "achievements_pool_min_items": game_config.ACHIEVEMENTS_POOL_MIN_ITEMS,
        "achievements_pool_gap_minutes": game_config.ACHIEVEMENTS_POOL_GAP_MINUTES,
        "contraband_daily_cap": game_config.CONTRABAND_DAILY_CAP,
        "voice_min_gap_hours": game_config.VOICE_TASK_MIN_GAP_HOURS,
        "music_weekday": game_config.MUSIC_DEFAULT_WEEKDAY,
        "music_hour": game_config.MUSIC_DEFAULT_HOUR,
        "music_game_weekday": game_config.MUSIC_GAME_DEFAULT_WEEKDAY,
        "music_game_hour": game_config.MUSIC_GAME_DEFAULT_HOUR,
    }


async def _get_int(
    session: AsyncSession, key: str, default: int, *, lo: int = 0, hi: int = 10000
) -> int:
    """Целое из конфига с зажимом в границы. Мусор → дефолт (не падаем)."""
    raw = await _get_value(session, key)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (ValueError, TypeError):
        log.warning("admin_config.bad_int", key=key, value=raw)
        return default
    return max(lo, min(hi, value))


async def get_game_digest_enabled(session: AsyncSession) -> bool:
    return await _get_bool(session, GAME_DIGEST_ENABLED_KEY, _GAME_DIGEST_ENABLED_DEFAULT)


async def get_game_digest_interval_hours(session: AsyncSession) -> int:
    from app.services.game.config import DIGEST_INTERVALS

    value = await _get_int(session, GAME_DIGEST_INTERVAL_KEY, _game_defaults()["digest_interval"])
    return value if value in DIGEST_INTERVALS else _game_defaults()["digest_interval"]


async def get_game_digest_last_flush(session: AsyncSession) -> str | None:
    """ISO-таймстемп последней сводки — чтобы понимать, не пора ли снова."""
    return await _get_value(session, GAME_DIGEST_LAST_FLUSH_KEY)


async def set_game_digest_last_flush(session: AsyncSession, value: str) -> None:
    await _set_value(session, GAME_DIGEST_LAST_FLUSH_KEY, value)


async def get_game_memorial_enabled(session: AsyncSession) -> bool:
    return await _get_bool(
        session, GAME_MEMORIAL_ENABLED_KEY, _GAME_MEMORIAL_ENABLED_DEFAULT
    )


async def get_game_memorial_silence_days(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_MEMORIAL_SILENCE_KEY, _game_defaults()["memorial_silence_days"], lo=1
    )


async def get_game_memorial_repeat_days(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_MEMORIAL_REPEAT_KEY, _game_defaults()["memorial_repeat_days"], lo=1
    )


async def get_game_events_enabled(session: AsyncSession) -> bool:
    return await _get_bool(session, GAME_EVENTS_ENABLED_KEY, _GAME_EVENTS_ENABLED_DEFAULT)


async def get_game_events_chance_percent(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_EVENTS_CHANCE_KEY, _game_defaults()["events_chance_percent"], hi=100
    )


async def get_game_events_max_per_day(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_EVENTS_MAX_PER_DAY_KEY, _game_defaults()["events_max_per_day"],
        hi=50,
    )


async def get_game_events_min_per_day(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_EVENTS_MIN_PER_DAY_KEY, _game_defaults()["events_min_per_day"],
        hi=50,
    )


async def get_game_events_day_start_hour(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_EVENTS_DAY_START_KEY, _game_defaults()["events_day_start_hour"],
        hi=23,
    )


async def get_game_events_day_end_hour(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_EVENTS_DAY_END_KEY, _game_defaults()["events_day_end_hour"],
        hi=24,
    )


async def get_game_events_min_gap_hours(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_EVENTS_MIN_GAP_KEY, _game_defaults()["events_min_gap_hours"]
    )


async def get_activity_day_start_hour(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_ACTIVITY_DAY_START_KEY, _game_defaults()["activity_day_start_hour"],
        hi=23,
    )


async def get_activity_day_end_hour(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_ACTIVITY_DAY_END_KEY, _game_defaults()["activity_day_end_hour"],
        hi=24,
    )


async def get_activity_quiet_minutes(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_ACTIVITY_QUIET_KEY, _game_defaults()["activity_quiet_minutes"],
        hi=240,
    )


async def get_activity_max_posts_per_day(session: AsyncSession) -> int:
    """Единый бюджет дня: 0 — без лимита, иначе максимум авто-постов за сутки."""
    return await _get_int(
        session,
        GAME_ACTIVITY_MAX_POSTS_KEY,
        _game_defaults()["activity_max_posts_per_day"],
        hi=200,
    )


async def get_achievements_post_mode(session: AsyncSession) -> str:
    """Режим публикации ачивок: `instant` (как раньше) или `pool` (буфер+сводка)."""
    from app.services.game.config import ACHIEVEMENT_POST_MODE, ACHIEVEMENT_POST_MODES

    raw = await _get_value(session, GAME_ACHIEVEMENTS_POST_MODE_KEY)
    value = (raw or "").strip().lower()
    return value if value in ACHIEVEMENT_POST_MODES else ACHIEVEMENT_POST_MODE


async def set_achievements_post_mode(session: AsyncSession, mode: str) -> None:
    from app.services.game.config import ACHIEVEMENT_POST_MODES

    value = (mode or "").strip().lower()
    if value not in ACHIEVEMENT_POST_MODES:
        value = ACHIEVEMENT_POST_MODES[0]
    await _set_value(session, GAME_ACHIEVEMENTS_POST_MODE_KEY, value)


async def get_chat_output_mode(session: AsyncSession) -> str:
    """Э20: режим вывода бота в основной чат (normal/achievements/all)."""
    from app.services.game.config import CHAT_OUTPUT_MODE, CHAT_OUTPUT_MODES

    raw = await _get_value(session, GAME_CHAT_OUTPUT_MODE_KEY)
    value = (raw or "").strip().lower()
    return value if value in CHAT_OUTPUT_MODES else CHAT_OUTPUT_MODE


async def set_chat_output_mode(session: AsyncSession, mode: str) -> None:
    from app.services.game.config import CHAT_OUTPUT_MODES

    value = (mode or "").strip().lower()
    if value not in CHAT_OUTPUT_MODES:
        value = CHAT_OUTPUT_MODES[0]
    await _set_value(session, GAME_CHAT_OUTPUT_MODE_KEY, value)


async def get_achievements_pool_interval_hours(session: AsyncSession) -> int:
    from app.services.game.config import ACHIEVEMENTS_POOL_INTERVALS

    default = _game_defaults()["achievements_pool_interval"]
    value = await _get_int(session, GAME_ACHIEVEMENTS_POOL_INTERVAL_KEY, default, lo=1, hi=24)
    return value if value in ACHIEVEMENTS_POOL_INTERVALS else default


async def get_achievements_pool_morning_hour(session: AsyncSession) -> int:
    return await _get_int(
        session,
        GAME_ACHIEVEMENTS_POOL_MORNING_KEY,
        _game_defaults()["achievements_pool_morning_hour"],
        hi=23,
    )


async def get_achievements_pool_min_items(session: AsyncSession) -> int:
    return await _get_int(
        session,
        GAME_ACHIEVEMENTS_POOL_MIN_ITEMS_KEY,
        _game_defaults()["achievements_pool_min_items"],
        hi=100,
    )


async def get_achievements_pool_gap_minutes(session: AsyncSession) -> int:
    return await _get_int(
        session,
        GAME_ACHIEVEMENTS_POOL_GAP_KEY,
        _game_defaults()["achievements_pool_gap_minutes"],
        hi=240,
    )


async def get_achievements_pool_last_flush(session: AsyncSession) -> str | None:
    return await _get_value(session, GAME_ACHIEVEMENTS_POOL_LAST_FLUSH_KEY)


async def set_achievements_pool_last_flush(session: AsyncSession, value: str) -> None:
    await _set_value(session, GAME_ACHIEVEMENTS_POOL_LAST_FLUSH_KEY, value)


async def set_achievements_pool_interval_hours(session: AsyncSession, hours: int) -> None:
    from app.services.game.config import ACHIEVEMENTS_POOL_INTERVALS

    default = _game_defaults()["achievements_pool_interval"]
    value = hours if hours in ACHIEVEMENTS_POOL_INTERVALS else default
    await _set_value(session, GAME_ACHIEVEMENTS_POOL_INTERVAL_KEY, str(value))


async def set_achievements_pool_morning_hour(session: AsyncSession, hour: int) -> None:
    await _set_value(
        session, GAME_ACHIEVEMENTS_POOL_MORNING_KEY, str(max(0, min(23, hour)))
    )


async def set_achievements_pool_min_items(session: AsyncSession, items: int) -> None:
    await _set_value(
        session, GAME_ACHIEVEMENTS_POOL_MIN_ITEMS_KEY, str(max(0, min(100, items)))
    )


async def set_achievements_pool_gap_minutes(session: AsyncSession, minutes: int) -> None:
    await _set_value(
        session, GAME_ACHIEVEMENTS_POOL_GAP_KEY, str(max(0, min(240, minutes)))
    )


async def get_game_contraband_enabled(session: AsyncSession) -> bool:
    return await _get_bool(
        session, GAME_CONTRABAND_ENABLED_KEY, _GAME_CONTRABAND_ENABLED_DEFAULT
    )


async def get_game_contraband_chance_percent(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_CONTRABAND_CHANCE_KEY, 100, hi=100
    )


async def get_game_contraband_daily_cap(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_CONTRABAND_CAP_KEY, _game_defaults()["contraband_daily_cap"], hi=100
    )


async def get_game_contraband_words(session: AsyncSession) -> list[dict] | None:
    """Пользовательский реестр слов. `None` = «не настроено, бери дефолтный».

    Пустой список — это НЕ «не настроено», а осознанное «правил нет»: админ
    мог вычистить реестр, и тогда контрабанда должна молчать, а не воскрешать
    дефолты из кода.
    """
    raw = await _get_value(session, GAME_CONTRABAND_WORDS_KEY)
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        log.warning("admin_config.bad_contraband_json")
        return None
    if not isinstance(parsed, list):
        return None
    return [item for item in parsed if isinstance(item, dict)]


async def set_game_contraband_words(session: AsyncSession, words: list[dict]) -> None:
    await _set_value(
        session,
        GAME_CONTRABAND_WORDS_KEY,
        json.dumps(words, ensure_ascii=False),
    )


async def get_game_voice_enabled(session: AsyncSession) -> bool:
    return await _get_bool(
        session, GAME_VOICE_ENABLED_KEY, _GAME_VOICE_ENABLED_DEFAULT
    )


async def get_game_voice_poll_enabled(session: AsyncSession) -> bool:
    return await _get_bool(session, GAME_VOICE_POLL_KEY, _GAME_VOICE_POLL_DEFAULT)


async def get_game_voice_min_gap_hours(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_VOICE_MIN_GAP_KEY, _game_defaults()["voice_min_gap_hours"], lo=1
    )


async def set_game_voice_enabled(session: AsyncSession, value: bool) -> None:
    await _set_value(session, GAME_VOICE_ENABLED_KEY, "true" if value else "false")


async def set_game_voice_poll_enabled(session: AsyncSession, value: bool) -> None:
    await _set_value(session, GAME_VOICE_POLL_KEY, "true" if value else "false")


async def set_game_voice_min_gap_hours(session: AsyncSession, hours: int) -> None:
    await _set_value(session, GAME_VOICE_MIN_GAP_KEY, str(max(1, int(hours))))


async def get_game_voice_alt_mode_enabled(session: AsyncSession) -> bool:
    return await _get_bool(
        session, GAME_VOICE_ALT_MODE_KEY, _GAME_VOICE_ALT_MODE_DEFAULT
    )


async def set_game_voice_alt_mode_enabled(session: AsyncSession, value: bool) -> None:
    await _set_value(session, GAME_VOICE_ALT_MODE_KEY, "true" if value else "false")


async def get_game_music_enabled(session: AsyncSession) -> bool:
    return await _get_bool(
        session, GAME_MUSIC_ENABLED_KEY, _GAME_MUSIC_ENABLED_DEFAULT
    )


async def get_game_music_weekday(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_MUSIC_WEEKDAY_KEY, _game_defaults()["music_weekday"], hi=6
    )


async def get_game_music_hour(session: AsyncSession) -> int:
    return await _get_int(
        session, GAME_MUSIC_HOUR_KEY, _game_defaults()["music_hour"], hi=23
    )


async def get_game_music_attribute(session: AsyncSession) -> bool:
    return await _get_bool(
        session, GAME_MUSIC_ATTRIBUTE_KEY, _GAME_MUSIC_ATTRIBUTE_DEFAULT
    )


async def set_game_music_enabled(session: AsyncSession, value: bool) -> None:
    await _set_value(session, GAME_MUSIC_ENABLED_KEY, "true" if value else "false")


async def set_game_music_attribute(session: AsyncSession, value: bool) -> None:
    await _set_value(session, GAME_MUSIC_ATTRIBUTE_KEY, "true" if value else "false")


def _clamp(value: int, *, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


async def set_game_music_weekday(session: AsyncSession, weekday: int) -> None:
    """День недели публикации (0=Пн). Чужие значения зажимаем в границы."""
    await _set_value(
        session, GAME_MUSIC_WEEKDAY_KEY, str(_clamp(weekday, lo=0, hi=6))
    )


async def set_game_music_hour(session: AsyncSession, hour: int) -> None:
    await _set_value(session, GAME_MUSIC_HOUR_KEY, str(_clamp(hour, lo=0, hi=23)))


async def get_game_music_game_enabled(session: AsyncSession) -> bool:
    return await _get_bool(
        session, GAME_MUSIC_GAME_ENABLED_KEY, _GAME_MUSIC_GAME_ENABLED_DEFAULT
    )


async def get_game_music_game_weekday(session: AsyncSession) -> int:
    return await _get_int(
        session,
        GAME_MUSIC_GAME_WEEKDAY_KEY,
        _game_defaults()["music_game_weekday"],
        hi=6,
    )


async def get_game_music_game_hour(session: AsyncSession) -> int:
    return await _get_int(
        session,
        GAME_MUSIC_GAME_HOUR_KEY,
        _game_defaults()["music_game_hour"],
        hi=23,
    )


async def set_game_music_game_enabled(session: AsyncSession, value: bool) -> None:
    await _set_value(
        session, GAME_MUSIC_GAME_ENABLED_KEY, "true" if value else "false"
    )


async def set_game_music_game_weekday(session: AsyncSession, weekday: int) -> None:
    await _set_value(
        session, GAME_MUSIC_GAME_WEEKDAY_KEY, str(_clamp(weekday, lo=0, hi=6))
    )


async def set_game_music_game_hour(session: AsyncSession, hour: int) -> None:
    await _set_value(
        session, GAME_MUSIC_GAME_HOUR_KEY, str(_clamp(hour, lo=0, hi=23))
    )


async def set_game_digest_enabled(session: AsyncSession, value: bool) -> None:
    await _set_value(session, GAME_DIGEST_ENABLED_KEY, "true" if value else "false")


async def set_game_digest_interval(session: AsyncSession, hours: int) -> None:
    """Интервал сводки. Чужие значения зажимаем к ближайшему допустимому."""
    from app.services.game.config import DIGEST_INTERVALS

    allowed = sorted(DIGEST_INTERVALS)
    if hours in allowed:
        chosen = hours
    else:
        chosen = min(allowed, key=lambda x: abs(x - hours))
    await _set_value(session, GAME_DIGEST_INTERVAL_KEY, str(chosen))


async def set_game_memorial_enabled(session: AsyncSession, value: bool) -> None:
    await _set_value(session, GAME_MEMORIAL_ENABLED_KEY, "true" if value else "false")


async def set_game_memorial_silence_days(session: AsyncSession, days: int) -> None:
    await _set_value(session, GAME_MEMORIAL_SILENCE_KEY, str(max(1, int(days))))


async def set_game_memorial_repeat_days(session: AsyncSession, days: int) -> None:
    await _set_value(session, GAME_MEMORIAL_REPEAT_KEY, str(max(1, int(days))))


async def set_game_events_enabled(session: AsyncSession, value: bool) -> None:
    await _set_value(session, GAME_EVENTS_ENABLED_KEY, "true" if value else "false")


async def set_game_events_chance_percent(session: AsyncSession, value: int) -> None:
    await _set_value(session, GAME_EVENTS_CHANCE_KEY, str(max(0, min(100, int(value)))))


async def set_game_events_max_per_day(session: AsyncSession, value: int) -> None:
    await _set_value(session, GAME_EVENTS_MAX_PER_DAY_KEY, str(max(0, int(value))))


async def set_game_events_min_per_day(session: AsyncSession, value: int) -> None:
    await _set_value(session, GAME_EVENTS_MIN_PER_DAY_KEY, str(max(0, int(value))))


async def set_game_events_day_start_hour(session: AsyncSession, value: int) -> None:
    await _set_value(session, GAME_EVENTS_DAY_START_KEY, str(max(0, min(23, int(value)))))


async def set_game_events_day_end_hour(session: AsyncSession, value: int) -> None:
    await _set_value(session, GAME_EVENTS_DAY_END_KEY, str(max(0, min(24, int(value)))))


async def set_game_events_min_gap_hours(session: AsyncSession, value: int) -> None:
    await _set_value(session, GAME_EVENTS_MIN_GAP_KEY, str(max(0, int(value))))


async def set_activity_day_start_hour(session: AsyncSession, value: int) -> None:
    await _set_value(session, GAME_ACTIVITY_DAY_START_KEY, str(max(0, min(23, int(value)))))


async def set_activity_day_end_hour(session: AsyncSession, value: int) -> None:
    await _set_value(session, GAME_ACTIVITY_DAY_END_KEY, str(max(0, min(24, int(value)))))


async def set_activity_quiet_minutes(session: AsyncSession, value: int) -> None:
    await _set_value(session, GAME_ACTIVITY_QUIET_KEY, str(max(0, int(value))))


async def set_activity_max_posts_per_day(session: AsyncSession, value: int) -> None:
    await _set_value(
        session, GAME_ACTIVITY_MAX_POSTS_KEY, str(max(0, min(200, int(value))))
    )


async def set_game_contraband_enabled(session: AsyncSession, value: bool) -> None:
    await _set_value(session, GAME_CONTRABAND_ENABLED_KEY, "true" if value else "false")


async def set_game_contraband_chance_percent(session: AsyncSession, value: int) -> None:
    await _set_value(session, GAME_CONTRABAND_CHANCE_KEY, str(max(0, min(100, int(value)))))


async def set_game_contraband_daily_cap(session: AsyncSession, value: int) -> None:
    await _set_value(session, GAME_CONTRABAND_CAP_KEY, str(max(0, int(value))))
