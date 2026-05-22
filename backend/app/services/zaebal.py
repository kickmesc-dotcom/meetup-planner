"""GHG6 E11 — /zaebal и /zaebal-vote: добровольное «бот, отдохни».

Два пути приостановки:

1. **`/zaebal` (порог)** — у каждого участника есть «голос» с лимитом 1/час
   (ring buffer в admin_config["zaebal.recent_votes"]). Когда уникальных
   голосов в окне ≥ `threshold` (default 2 из 5 живых) — стартует пауза на
   `duration_days` (default 3) с reason="zaebal_threshold".

2. **`/zaebal-vote` (полл)** — создаёт Telegram-полл с `open_period =
   poll_hours * 3600`. После закрытия в `poll_answer.py` проверяется,
   набралось ли большинство голосов «за» — если да, пауза на
   `vote_duration_days` (default 7) с reason="zaebal_vote".

3. **`run_auto_zaebal(session, bot)`** — раз в месяц scheduler-job создаёт
   опрос от лица бота. Default off (E11.3).

Прощальные фразы — массив, выбирается случайно.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.admin_config import _get_value, _set_value
from app.services.bot_pause import (
    get_active_pause,
    get_zaebal_settings,
    start_pause,
)

log = structlog.get_logger()

ZAEBAL_VOTES_BUFFER_KEY = "zaebal.recent_votes"          # JSON: [{ts, tg_id}]
ZAEBAL_VOTE_WINDOW_MINUTES = 60
ZAEBAL_ACTIVE_POLL_KEY = "zaebal.active_poll"             # JSON: {tg_poll_id, tg_message_id, kind, vote_duration_days, created_at}

FAREWELL_PHRASES = [
    "I'll be back.",
    "Я вернусь, сучки.",
    "И ты, Брут.",
    "Молчу, обиделся.",
    "Хорошо, сами поскучайте без меня.",
    "Окей, ушёл в астрал. Чмок.",
]


def _farewell_phrase() -> str:
    return random.choice(FAREWELL_PHRASES)


# --- /zaebal порог ----------------------------------------------------------


def _within_window(ts_iso: str, now: datetime, window_min: int) -> bool:
    try:
        ts = datetime.fromisoformat(ts_iso)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= now - timedelta(minutes=window_min)


async def _load_votes(session: AsyncSession) -> list[dict[str, Any]]:
    raw = await _get_value(session, ZAEBAL_VOTES_BUFFER_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [v for v in data if isinstance(v, dict)]
    except (ValueError, TypeError):
        pass
    return []


async def _save_votes(session: AsyncSession, votes: list[dict[str, Any]]) -> None:
    await _set_value(session, ZAEBAL_VOTES_BUFFER_KEY, json.dumps(votes))


def count_unique_voters_in_window(
    votes: list[dict[str, Any]], now: datetime, window_min: int
) -> set[int]:
    """Чистая функция для теста: множество tg_id, голосовавших в окне."""
    out: set[int] = set()
    for v in votes:
        ts_iso = v.get("ts")
        tg_id = v.get("tg_id")
        if not isinstance(ts_iso, str) or not isinstance(tg_id, int):
            continue
        if _within_window(ts_iso, now, window_min):
            out.add(tg_id)
    return out


async def register_zaebal_vote(
    session: AsyncSession, *, tg_id: int
) -> tuple[int, int]:
    """Регистрирует голос /zaebal. Возвращает (current_count, threshold).
    Сам не стартует паузу — это делает handler, который смотрит на возврат."""
    now = datetime.now(timezone.utc)
    votes = await _load_votes(session)
    # Чистим старые сразу — буфер не растёт.
    votes = [
        v for v in votes
        if _within_window(v.get("ts", ""), now, ZAEBAL_VOTE_WINDOW_MINUTES)
    ]
    # Один tg_id в окне = один голос: удаляем дубли, перезаписываем актуальным ts.
    votes = [v for v in votes if v.get("tg_id") != tg_id]
    votes.append({"ts": now.isoformat(), "tg_id": tg_id})
    await _save_votes(session, votes)

    settings = await get_zaebal_settings(session)
    unique = count_unique_voters_in_window(votes, now, ZAEBAL_VOTE_WINDOW_MINUTES)
    return len(unique), int(settings["threshold"])


async def clear_zaebal_votes(session: AsyncSession) -> None:
    await _save_votes(session, [])


# --- /zaebal-vote (Telegram-полл) -------------------------------------------


async def create_zaebal_poll(
    session: AsyncSession,
    bot: Bot,
    *,
    initiator_label: str,
    auto: bool = False,
) -> dict[str, Any] | None:
    """Создаёт Telegram-полл, сохраняет активный poll в admin_config.
    Возвращает payload активного полла или None при ошибке."""
    settings = get_settings()
    if not settings.group_chat_id:
        log.warning("zaebal.no_group_chat_id")
        return None
    if await get_active_pause(session) is not None:
        log.info("zaebal.already_paused")
        return None
    cfg = await get_zaebal_settings(session)
    open_period = max(60, int(cfg["poll_hours"]) * 3600)
    if auto:
        question = "Друзьяшечки-братушечки, отвечаем честно — заебал?"
    else:
        question = f"{initiator_label} спрашивает: GHG Bot — zaebal?"
    try:
        msg = await bot.send_poll(
            chat_id=settings.group_chat_id,
            question=question,
            options=["Да, заткни его", "Нет, пускай продолжает"],
            is_anonymous=False,
            allows_multiple_answers=False,
            open_period=open_period,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("zaebal.poll_send_failed", error=str(exc))
        return None
    poll = msg.poll
    if poll is None:
        return None
    payload = {
        "tg_poll_id": poll.id,
        "tg_message_id": msg.message_id,
        "auto": auto,
        "vote_duration_days": int(cfg["vote_duration_days"]),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await _set_value(session, ZAEBAL_ACTIVE_POLL_KEY, json.dumps(payload))
    return payload


async def get_active_zaebal_poll(session: AsyncSession) -> dict[str, Any] | None:
    raw = await _get_value(session, ZAEBAL_ACTIVE_POLL_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


async def clear_active_zaebal_poll(session: AsyncSession) -> None:
    await _set_value(session, ZAEBAL_ACTIVE_POLL_KEY, "")


def decide_zaebal_poll_outcome(
    yes_votes: int, no_votes: int
) -> bool:
    """Чистая функция: True если большинство «за» (yes > no).
    Ничья — не приостанавливаем."""
    return yes_votes > no_votes


async def handle_zaebal_poll_closed(
    session: AsyncSession,
    *,
    tg_poll_id: str,
    yes_votes: int,
    no_votes: int,
) -> bool:
    """Вызывается из poll_answer handler при закрытии полла. Если это
    наш zaebal-полл и большинство «за» — стартуем паузу. Возвращает True
    если пауза стартовала."""
    active = await get_active_zaebal_poll(session)
    if not active or active.get("tg_poll_id") != tg_poll_id:
        return False
    await clear_active_zaebal_poll(session)
    if not decide_zaebal_poll_outcome(yes_votes, no_votes):
        log.info("zaebal.poll_lost", yes=yes_votes, no=no_votes)
        return False
    duration_days = int(active.get("vote_duration_days", 7))
    try:
        await start_pause(
            session,
            duration_days=duration_days,
            reason="zaebal_vote",
            started_by_tg_id=None,
        )
    except ValueError as exc:
        log.info("zaebal.start_pause_failed", error=str(exc))
        return False
    return True


# --- Auto-zaebal ------------------------------------------------------------


async def run_auto_zaebal(session: AsyncSession, bot: Bot) -> None:
    """Scheduler-job: запускает /zaebal-vote от лица бота. Идемпотентность —
    через TG-полл (создаётся ≤1 раз в день; APScheduler сам не дублирует, но
    если бот рестартовал и job выстрелил повторно — get_active_zaebal_poll
    защитит от двойного полла)."""
    active = await get_active_zaebal_poll(session)
    if active is not None:
        log.info("zaebal.auto_skipped_active_poll")
        return
    await create_zaebal_poll(session, bot, initiator_label="🤖 Бот", auto=True)
