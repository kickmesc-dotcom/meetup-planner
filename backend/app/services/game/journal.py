"""GHG10 Э13: игровой журнал — одна дверь для всего, что бот пишет в чат.

Задача от заказчика: «я боюсь, что когда народ начнёт массово левел-апиться,
в чате начнётся дикий спам от бота. Давай сделаем альтернативный режим, когда
бот ловит события в мини-журнал и потом выплёвывает как сводку (кто чего
открыл, насколько прокачался, какой гет получил) — каждый час, 6ч, 12ч, сутки,
но пока этот режим неактивен».

Поэтому все игровые анонсы (ачивки, праздники, случайные события, контрабанда)
идут через `announce`, и только он решает: сказать сейчас или положить в
`game_journal` до ближайшего окна сводки.

Три правила модуля:

1. **Никаких исключений наружу.** Анонс — украшение, а не работа. Любой сбой
   TG/БД логируется и возвращает `False`.
2. **Журнал — не очередь «доставить во что бы то ни стало».** Событие, которое
   не переживёт рестарт, не стоит того, чтобы городить надёжную доставку: строки
   просто лежат в таблице и уходят следующим окном.
3. **Сводка не раздувается.** Если накопилось больше, чем влезает в одно
   сообщение Telegram, режем на несколько — но не теряем содержимое.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import GameJournalEntry
from app.services.admin_config import (
    get_game_digest_enabled,
    get_game_digest_interval_hours,
    get_game_digest_last_flush,
    set_game_digest_last_flush,
)
from app.services.game.config import DIGEST_MAX_CHARS

log = structlog.get_logger()

# Виды записей. Строки стабильны: они лежат в БД, поэтому переименование кода
# сломало бы чтение уже накопленных строк.
KIND_ACHIEVEMENT = "achievement"
KIND_HOLIDAY = "holiday"
KIND_EVENT = "event"
KIND_CONTRABAND = "contraband"
KIND_MEMORIAL = "memorial"
KIND_OTHER = "other"

# Как вид записи выглядит в сводке.
KIND_LABELS: dict[str, tuple[str, str]] = {
    KIND_ACHIEVEMENT: ("🏆", "Ачивки"),
    KIND_HOLIDAY: ("🎊", "Праздники"),
    KIND_EVENT: ("⚡️", "События"),
    KIND_CONTRABAND: ("💰", "Контрабанда"),
    KIND_MEMORIAL: ("🕯", "Поминовения"),
    KIND_OTHER: ("📌", "Прочее"),
}

DIGEST_HEADER = "🗞 <b>Сводка</b>"


def _get_bot():
    """Ленивая добыча бота (импорт внутри — иначе цикл dispatcher → handlers)."""
    try:
        from app.bot.dispatcher import get_bot

        return get_bot()
    except Exception:  # noqa: BLE001
        return None


async def _achievements_markup():
    """Кнопка «свои ачивки» для сводки. None, если её не собрать."""
    try:
        from app.services.game.achievements import achievements_url

        bot = _get_bot()
        url = await achievements_url(bot)
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🏆 Свои ачивки", url=url)]]
        )
    except Exception:  # noqa: BLE001
        return None


async def send_now(
    text: str,
    *,
    chat_id: int | None = None,
    reply_markup=None,
) -> bool:
    """Прямая отправка в чат. Best-effort, без исключений наружу."""
    settings = get_settings()
    target = chat_id or settings.group_chat_id
    if not target or not text:
        return False
    bot = _get_bot()
    if bot is None:
        return False
    try:
        kwargs = {"chat_id": target, "text": text, "parse_mode": "HTML"}
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        await bot.send_message(**kwargs)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("game.journal_send_failed", error=str(exc))
        return False


async def announce(
    session: AsyncSession,
    *,
    kind: str,
    text: str,
    subject_user_id: int | None = None,
    chat_id: int | None = None,
    reply_markup=None,
) -> bool:
    """Единственная точка анонса игровых событий.

    Режим сводки выключен (по умолчанию) → отправляем сразу, как раньше.
    Включён → кладём в журнал; текст уйдёт следующим окном, кнопки в сводке
    общие (одна «свои ачивки» на всё сообщение).
    """
    if not text:
        return False
    try:
        if not await get_game_digest_enabled(session):
            return await send_now(text, chat_id=chat_id, reply_markup=reply_markup)
        # `chat_id` намеренно не подставляем из настроек здесь: сводка уедет
        # туда, где чат актуален НА МОМЕНТ отправки, а не на момент события.
        entry = GameJournalEntry(
            kind=kind,
            text=text,
            subject_user_id=subject_user_id,
            chat_id=chat_id,
        )
        session.add(entry)
        await session.commit()
        log.info("game.journal_queued", kind=kind, subject_user_id=subject_user_id)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("game.journal_announce_failed", kind=kind, error=str(exc))
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


def build_digest_text(entries: list[dict], *, interval_hours: int | None = None) -> str:
    """Собрать текст сводки. Чистая функция — тестируется без БД и сети.

    `entries` — список `{"kind": str, "text": str}` в хронологическом порядке.
    Одинаковые виды группируются под одним ярлыком: «🏆 Ачивки», «💰 Контрабанда».
    """
    if not entries:
        return ""
    title = DIGEST_HEADER
    if interval_hours:
        title += f" за {interval_hours} ч"
    out: list[str] = [title]
    current_kind: str | None = None
    for entry in entries:
        kind = entry.get("kind") or KIND_OTHER
        if kind != current_kind:
            icon, label = KIND_LABELS.get(kind, KIND_LABELS[KIND_OTHER])
            out.append(f"{icon} <b>{label}</b>")
            current_kind = kind
        out.append((entry.get("text") or "").strip())
    return "\n".join(out).strip()


def chunk_digest(text: str, *, limit: int = DIGEST_MAX_CHARS) -> list[str]:
    """Порезать сводку по границам строк так, чтобы влезла в сообщение TG.

    Делегирует в общий для чат-текстов резак (`report.chunk_text`), чтобы
    правило «сколько символов влезает» жило в одном месте.
    """
    from app.services.game import report

    return report.chunk_text(text, limit=limit)


async def pending_entries(session: AsyncSession, *, limit: int = 200) -> list[GameJournalEntry]:
    """Неотправленные записи журнала, от старых к новым."""
    rows = await session.scalars(
        select(GameJournalEntry)
        .where(GameJournalEntry.sent_at.is_(None))
        .order_by(GameJournalEntry.created_at.asc(), GameJournalEntry.id.asc())
        .limit(limit)
    )
    return list(rows)


async def flush(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Отправить накопленное одним сообщением (или несколькими).

    Возвращает число отправленных записей: 0 — если отправлять нечего или
    Telegram не принял (тогда записи остаются в журнале до следующего окна).
    """
    moment = now or datetime.now(timezone.utc)
    rows = await pending_entries(session)
    if not rows:
        return 0
    interval = await get_game_digest_interval_hours(session)
    payload = [{"kind": r.kind, "text": r.text} for r in rows]
    markup = await _achievements_markup()
    # Если все записи адресованы одному чату — отправляем туда, иначе в общий.
    chats = {r.chat_id for r in rows}
    target = chats.pop() if len(chats) == 1 else None
    sent_any = False
    for chunk in chunk_digest(build_digest_text(payload, interval_hours=interval)):
        ok = await send_now(
            chunk, chat_id=target, reply_markup=markup if not sent_any else None
        )
        if not ok:
            return 0  # ничего не пометили — попробуем следующим окном
        sent_any = True
    for row in rows:
        row.sent_at = moment
    await session.commit()
    await set_game_digest_last_flush(session, moment.isoformat())
    log.info("game.digest_flushed", entries=len(rows))
    return len(rows)


async def digest_due(session: AsyncSession, *, now: datetime | None = None) -> bool:
    """Пора ли вываливать сводку: прошло не меньше настроенного интервала."""
    interval = await get_game_digest_interval_hours(session)
    raw = await get_game_digest_last_flush(session)
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    moment = now or datetime.now(timezone.utc)
    return moment - last >= timedelta(hours=interval)


async def run_digest_job(now: datetime | None = None) -> int:
    """Job планировщика: если режим включён и интервал истёк — отправить сводку.

    Job тикает чаще самого большого интервала (раз в час), а решение «пора/не
    пора» принимает сам: иначе правка интервала в админке требовала бы
    пересоздания job'а, а `reload_dynamic_jobs` дёргается не каждый раз.
    """
    from app.db.base import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as session:
        if not await get_game_digest_enabled(session):
            return 0
        if not await digest_due(session, now=now):
            return 0
        return await flush(session, now=now)
