"""GHG8 P7: пул шуток на «мёртвый чат».

Если в группе долго нет активности (ни текста, ни медиа от участников), бот
раз в час проверяет тишину и при пересечении очередного порога постит фразу
из пула этого порога. Эскалация: 24ч → 72ч → неделя → месяц → полгода → год
(безобидные → философские). Анти-спам: на каждый порог — максимум один пост
за «окно тишины»; любое живое сообщение открывает новое окно.

Хранение — admin_config, БЕЗ миграции (решение пользователя 2026-06-07,
паттерн P5/Q7.b: фраз немного, шестёрке друзей таблица не нужна):
- `dead_chat.enabled` — master-toggle (default true);
- `dead_chat.phrases` — JSON {threshold: [фразы]}; дефолты в коде
  подхватываются для порогов, отсутствующих в ключе (паттерн loser_reasons);
- `dead_chat.last_activity_at` — ISO-метка последнего живого сообщения
  (текст ИЛИ медиа — решение пользователя). Пишется из chat_capture и
  media_reactions с in-memory-троттлингом (персист не чаще раза в 15 минут:
  пороги начинаются с 24ч, точнее не нужно — бережём Neon);
- `dead_chat.last_post` — JSON {"threshold", "activity_at"} последнего поста
  (якорь анти-спама: activity_at идентифицирует окно тишины).

История сообщений тут НЕ используется: ChatMessage живёт 7 дней
(chat_capture.RETENTION_DAYS), а пороги — до года, поэтому единственный
источник правды о тишине — персистнутая метка.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.services.admin_config import _get_bool, _get_value, _set_value

log = structlog.get_logger()

DEAD_CHAT_ENABLED_KEY = "dead_chat.enabled"
DEAD_CHAT_PHRASES_KEY = "dead_chat.phrases"
DEAD_CHAT_LAST_ACTIVITY_KEY = "dead_chat.last_activity_at"
DEAD_CHAT_LAST_POST_KEY = "dead_chat.last_post"

_ENABLED_DEFAULT = True

# Пороги тишины по возрастанию: (ключ, часы). Ключи — стабильные id для
# admin_config/фраз, не переименовывать.
THRESHOLDS: tuple[tuple[str, float], ...] = (
    ("24h", 24.0),
    ("72h", 72.0),
    ("week", 7 * 24.0),
    ("month", 30 * 24.0),
    ("half_year", 182 * 24.0),
    ("year", 365 * 24.0),
)
_THRESHOLD_INDEX = {key: i for i, (key, _) in enumerate(THRESHOLDS)}

# Дефолтные пулы (GHG7.txt стр. 200–201: «начиная с безобидных… заканчивая
# философскими»). Цитаты пользователя сохранены дословно.
DEFAULT_PHRASES: dict[str, list[str]] = {
    "24h": [
        "Я что-то грубое сказал?",
        "Кто скажет слово — дохлая корова 🐄",
        "Промолчи, если не любишь маму.",
        "Алло, это чат или музей тишины?",
        "Сутки тишины. Объявляю минуту молчания по чувству юмора этого чата.",
    ],
    "72h": [
        "Трое суток тишины. Если вы играете в прятки — вы выиграли.",
        "День третий. Запасы мемов на исходе, моральный дух падает.",
        "72 часа без сообщений. Я уже начал разговаривать сам с собой.",
        "Это уже не пауза, это бойкот. Кто кого обидел?",
    ],
    "week": [
        "Неделя тишины. Объявляю чат заповедником редких молчунов.",
        "Семь дней. Я выучил все ваши старые сообщения наизусть. Пересказать?",
        "Неделя без сообщений. Голубиная почта и та живее.",
        "Если это коллективный ретрит — поздравляю, вы достигли просветления.",
    ],
    "month": [
        "Месяц тишины. Перебираю старые мемы, как фотоальбом. Хорошие были времена.",
        "30 дней. Начал писать мемуары: «Чат, который замолчал».",
        "Месяц без активности. Даже спам-боты сюда больше не заходят.",
    ],
    "half_year": [
        "Полгода. Я видел цивилизации, которые рождались и умирали быстрее, чем вы отвечаете.",
        "Шесть месяцев тишины. Зато ни одного конфликта — стабильность!",
        "Полгода молчания. Лучшая шутка этого чата — само его существование.",
    ],
    "year": [
        "Мне нравится представлять, что человечество вымерло и от участников "
        "этого чата давно остались только радиоактивные осадки. Но я слишком "
        "люблю свою работу.",
        "365 дней. Если кто-то это читает — передай потомкам: здесь когда-то смеялись.",
        "Год. Я — вечный смотритель маяка в море вашего молчания.",
    ],
}


# --- Чистые функции (юнит-тестируемые без БД) ---

def parse_phrases(raw: str | None) -> dict[str, list[str]]:
    """JSON из admin_config → {threshold: [фразы]}; для отсутствующих/кривых
    порогов — дефолты из кода (паттерн loser_reasons: новые фразы в коде
    подхватываются, пока админ не кастомизировал порог)."""
    custom: dict = {}
    if raw is not None:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                custom = data
        except (ValueError, TypeError):
            pass
    out: dict[str, list[str]] = {}
    for key, _ in THRESHOLDS:
        val = custom.get(key)
        if isinstance(val, list) and all(isinstance(x, str) for x in val):
            cleaned = [x.strip() for x in val if x.strip()]
            out[key] = cleaned if cleaned else list(DEFAULT_PHRASES[key])
        else:
            out[key] = list(DEFAULT_PHRASES[key])
    return out


def parse_last_post(raw: str | None) -> tuple[str, str] | None:
    """JSON → (threshold, activity_at_iso) или None (нет/невалидно)."""
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    th = data.get("threshold")
    at = data.get("activity_at")
    if th not in _THRESHOLD_INDEX or not isinstance(at, str):
        return None
    return th, at


def pick_threshold(
    silence_hours: float,
    last_post: tuple[str, str] | None,
    activity_at_iso: str,
) -> str | None:
    """Порог, по которому пора постить, или None.

    - Берём САМЫЙ ГЛУБОКИЙ достигнутый порог (если бот был офлайн и тишина
      проскочила 24h и 72h — постим один раз по 72h, не очередью).
    - Анти-спам: если последний пост был в ЭТОМ ЖЕ окне тишины (совпадает
      activity_at) на этом или более глубоком пороге — молчим. Эскалация
      внутри окна разрешена: 24h-пост не блокирует будущий 72h-пост.
    - Новая активность меняет activity_at → старый last_post не матчится,
      окно анти-спама открывается заново.
    """
    reached: str | None = None
    for key, hours in THRESHOLDS:
        if silence_hours >= hours:
            reached = key
    if reached is None:
        return None
    if last_post is not None:
        posted_th, posted_at = last_post
        if posted_at == activity_at_iso and (
            _THRESHOLD_INDEX[posted_th] >= _THRESHOLD_INDEX[reached]
        ):
            return None
    return reached


def pick_phrase(
    phrases: dict[str, list[str]], threshold: str, rng: random.Random | None = None
) -> str | None:
    pool = phrases.get(threshold) or []
    if not pool:
        return None
    return (rng or random).choice(pool)


# --- get/set admin_config ---

async def get_dead_chat_enabled(session: AsyncSession) -> bool:
    return await _get_bool(session, DEAD_CHAT_ENABLED_KEY, _ENABLED_DEFAULT)


async def set_dead_chat_enabled(session: AsyncSession, enabled: bool) -> None:
    await _set_value(session, DEAD_CHAT_ENABLED_KEY, "true" if enabled else "false")


async def get_dead_chat_phrases(session: AsyncSession) -> dict[str, list[str]]:
    return parse_phrases(await _get_value(session, DEAD_CHAT_PHRASES_KEY))


async def set_dead_chat_phrases(
    session: AsyncSession, phrases: dict[str, list[str]]
) -> None:
    # Сохраняем только известные пороги; чистка/дедуп — на стороне parse.
    payload = {k: v for k, v in phrases.items() if k in _THRESHOLD_INDEX}
    await _set_value(
        session, DEAD_CHAT_PHRASES_KEY, json.dumps(payload, ensure_ascii=False)
    )


# --- персист «последней активности» (вызывается из handlers) ---

# In-memory троттлинг персиста: пороги — от 24ч, поэтому точность метки в
# 15 минут достаточна, а Neon не получает лишний UPSERT на каждое сообщение
# активного чата (chat_capture и так делает INSERT+DELETE на сообщение).
_TOUCH_MIN_INTERVAL = timedelta(minutes=15)
_last_touch: datetime | None = None


async def touch_chat_activity(now: datetime | None = None) -> None:
    """Отметить живое сообщение (текст/медиа от участника). Best-effort:
    сбой Neon не должен ломать вызывающий handler — глотаем с warning."""
    global _last_touch
    at = now or datetime.now(timezone.utc)
    if _last_touch is not None and at - _last_touch < _TOUCH_MIN_INTERVAL:
        return
    _last_touch = at
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            await _set_value(session, DEAD_CHAT_LAST_ACTIVITY_KEY, at.isoformat())
    except Exception as exc:  # noqa: BLE001
        log.warning("dead_chat.touch_failed", error=str(exc))


# --- job ---

def _send_timeout() -> float:
    """Зеркало chukhan/_media_send_timeout — общий env LOSER_SEND_TIMEOUT."""
    raw = os.getenv("LOSER_SEND_TIMEOUT")
    if raw is None:
        return 25.0
    try:
        return float(int(raw))
    except ValueError:
        return 25.0


async def run_dead_chat_job(bot) -> None:
    """Часовой тик: проверить тишину, при пересечении порога — пост.

    Дёшево для Neon: 3–4 point-SELECT по admin_config; пост — редкое событие.
    """
    settings = get_settings()
    if not settings.group_chat_id:
        return

    sm = get_sessionmaker()
    async with sm() as session:
        if not await get_dead_chat_enabled(session):
            return
        # Глобальная пауза (/zaebal и пр.): «бот, помолчи» распространяется и
        # на пинание мёртвого чата — иначе пауза выглядит как повод для шутки.
        from app.services.bot_pause import is_paused

        if await is_paused(session):
            log.info("dead_chat.skipped_paused")
            return

        now = datetime.now(timezone.utc)
        raw_activity = await _get_value(session, DEAD_CHAT_LAST_ACTIVITY_KEY)
        if raw_activity is None:
            # Первый запуск после деплоя: метки нет — считаем «активность
            # сейчас», чтобы не постить по фантомной тишине года.
            await _set_value(
                session, DEAD_CHAT_LAST_ACTIVITY_KEY, now.isoformat()
            )
            log.info("dead_chat.activity_initialized")
            return
        try:
            activity_at = datetime.fromisoformat(raw_activity)
        except ValueError:
            log.warning("dead_chat.bad_activity_value", raw=raw_activity)
            await _set_value(
                session, DEAD_CHAT_LAST_ACTIVITY_KEY, now.isoformat()
            )
            return

        silence_hours = (now - activity_at).total_seconds() / 3600.0
        last_post = parse_last_post(
            await _get_value(session, DEAD_CHAT_LAST_POST_KEY)
        )
        threshold = pick_threshold(silence_hours, last_post, raw_activity)
        if threshold is None:
            return

        phrase = pick_phrase(await get_dead_chat_phrases(session), threshold)
        if phrase is None:
            log.info("dead_chat.empty_pool", threshold=threshold)
            return

        # Пост. При фейле send last_post НЕ пишем — следующий часовой тик
        # повторит попытку сам (естественный ретрай, как chukhan_retry).
        try:
            await asyncio.wait_for(
                bot.send_message(chat_id=settings.group_chat_id, text=phrase),
                timeout=_send_timeout(),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "dead_chat.send_failed", threshold=threshold, error=str(exc)
            )
            return

        await _set_value(
            session,
            DEAD_CHAT_LAST_POST_KEY,
            json.dumps({"threshold": threshold, "activity_at": raw_activity}),
        )
        log.info(
            "dead_chat.posted",
            threshold=threshold,
            silence_hours=round(silence_hours, 1),
        )
