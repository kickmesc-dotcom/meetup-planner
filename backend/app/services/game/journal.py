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

import re
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import GameJournalEntry, User
from app.services.admin_config import (
    get_achievements_pool_gap_minutes,
    get_achievements_pool_interval_hours,
    get_achievements_pool_last_flush,
    get_achievements_pool_min_items,
    get_achievements_pool_morning_hour,
    get_game_digest_enabled,
    get_game_digest_interval_hours,
    get_game_digest_last_flush,
    set_achievements_pool_last_flush,
    set_game_digest_last_flush,
)
from app.services.game.config import (
    ACHIEVEMENTS_POOL_RESERVED_SLOTS,
    ACTIVITY_TZ_OFFSET_HOURS,
    DIGEST_MAX_CHARS,
)

log = structlog.get_logger()

# Виды записей. Строки стабильны: они лежат в БД, поэтому переименование кода
# сломало бы чтение уже накопленных строк.
KIND_ACHIEVEMENT = "achievement"
KIND_ACHIEVEMENT_POOL = "achievement_pool"
KIND_HOLIDAY = "holiday"
KIND_EVENT = "event"
KIND_CONTRABAND = "contraband"
KIND_MEMORIAL = "memorial"
KIND_OTHER = "other"

# Как вид записи выглядит в сводке.
KIND_LABELS: dict[str, tuple[str, str]] = {
    KIND_ACHIEVEMENT: ("🏆", "Ачивки"),
    KIND_ACHIEVEMENT_POOL: ("🏆", "Ачивки"),
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


async def pending_entries(
    session: AsyncSession,
    *,
    limit: int = 200,
    kinds: tuple[str, ...] | None = None,
    exclude_kinds: tuple[str, ...] = (KIND_ACHIEVEMENT_POOL,),
) -> list[GameJournalEntry]:
    """Неотправленные записи журнала, от старых к новым.

    `kinds` — брать только эти виды (пул ачивок ходит за своими).
    `exclude_kinds` — наоборот, не брать: общая сводка (`flush`) не должна
    вытаскивать записи буфера ачивок, у них собственный расписанный выплеск.
    """
    stmt = select(GameJournalEntry).where(GameJournalEntry.sent_at.is_(None))
    if kinds is not None:
        stmt = stmt.where(GameJournalEntry.kind.in_(kinds))
    elif exclude_kinds:
        stmt = stmt.where(GameJournalEntry.kind.notin_(exclude_kinds))
    rows = await session.scalars(
        stmt.order_by(GameJournalEntry.created_at.asc(), GameJournalEntry.id.asc()).limit(limit)
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


# ==========================================================================
# Э19: буфер ачивок — «тихо копим, потом выплёскиваем одной сводкой»
# ==========================================================================

ACHIEVEMENTS_DIGEST_HEADER = "📈 <b>Сводка достижений</b>"

# Формат строки буфера, которую кладёт `achievements.announce_granted`:
#   «Успешный успех» (+50 XP)
_LINE_RE = re.compile(r"«(.+?)»\s*\(\+(\d+) XP\)")


def parse_achievement_line(line: str) -> tuple[str, int]:
    """Разобрать строку буфера на название и очки. Чистая функция.

    Формат генерим мы сами, поэтому разбор надёжен; на всякий случай кривая
    строка не теряется — возвращаем её целиком с нулём очков.
    """
    match = _LINE_RE.search(line or "")
    if match:
        return match.group(1), int(match.group(2))
    return (line or "").strip(), 0


def build_achievements_digest(groups: list[dict], *, interval_hours: int | None = None) -> str:
    """Собрать компактную сводку ачивок, сгруппированную по игроку.

    `groups` — список `{"name": str, "lines": [str]}`. Один человек — одна
    строка: «Митян получает ачивки: «...», «...» (+100 XP)». Чистая функция.
    """
    if not groups:
        return ""
    title = ACHIEVEMENTS_DIGEST_HEADER
    if interval_hours:
        title += f" за {interval_hours} ч"
    out: list[str] = [title]
    for group in groups:
        name = group.get("name") or "Участник"
        titles: list[str] = []
        total = 0
        for line in group.get("lines") or []:
            title_text, points = parse_achievement_line(line)
            titles.append(f"«{title_text}»")
            total += points
        if not titles:
            continue
        if len(titles) == 1:
            out.append(f"<b>{name}</b> получает ачивку {titles[0]} (+{total} XP)")
        else:
            out.append(
                f"<b>{name}</b> получает ачивки: {', '.join(titles)} (+{total} XP)"
            )
    return "\n".join(out).strip()


def local_minute_of_day(now: datetime, *, tz_offset: int = ACTIVITY_TZ_OFFSET_HOURS) -> int:
    """Минута локальных суток (UTC + смещение). Чистая функция."""
    local = now.astimezone(timezone.utc) + timedelta(hours=tz_offset)
    return local.hour * 60 + local.minute


def local_weekday(now: datetime, *, tz_offset: int = ACTIVITY_TZ_OFFSET_HOURS) -> int:
    """День недели локального времени (0 = понедельник). Чистая функция."""
    local = now.astimezone(timezone.utc) + timedelta(hours=tz_offset)
    return local.weekday()


def in_reserved_gap(
    now: datetime,
    *,
    slots: tuple[tuple[int, int, int], ...] = ACHIEVEMENTS_POOL_RESERVED_SLOTS,
    gap_minutes: int,
    tz_offset: int = ACTIVITY_TZ_OFFSET_HOURS,
) -> bool:
    """True, если сейчас слишком близко к критическому слоту (±`gap_minutes`).

    Именно здесь живёт «не столкнуться с понедельничным ивентом в 12:00»: слот
    имеет приоритет, а сводка ачивок сдвигается на следующий тик.
    """
    if gap_minutes <= 0:
        return False
    weekday = local_weekday(now, tz_offset=tz_offset)
    minute = local_minute_of_day(now, tz_offset=tz_offset)
    for slot_weekday, hour, minute_of_hour in slots:
        if slot_weekday != weekday:
            continue
        if abs(minute - (hour * 60 + minute_of_hour)) < gap_minutes:
            return True
    return False


async def queue_achievements(
    session: AsyncSession,
    *,
    user_id: int,
    lines: list[str],
    chat_id: int | None = None,
) -> bool:
    """Положить ачивки игрока в буфер. Best-effort, без исключений наружу.

    Одна строка буфера на ачивку: при выплеске они группируются по игроку и
    суммируют очки. `send_at` не трогаем — выплеснет расписание.
    """
    if not lines:
        return False
    try:
        for line in lines:
            session.add(
                GameJournalEntry(
                    kind=KIND_ACHIEVEMENT_POOL,
                    text=line,
                    subject_user_id=user_id,
                    chat_id=chat_id,
                )
            )
        await session.commit()
        log.info("game.achievements_queued", user_id=user_id, count=len(lines))
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("game.achievements_queue_failed", user_id=user_id, error=str(exc))
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


async def pool_pending_count(session: AsyncSession) -> int:
    """Сколько ачивок ждёт выплеска (для админки и решения «пора ли»)."""
    rows = await session.scalars(
        select(GameJournalEntry.id).where(
            GameJournalEntry.sent_at.is_(None),
            GameJournalEntry.kind == KIND_ACHIEVEMENT_POOL,
        )
    )
    return len(list(rows))


async def achievements_digest_due(session: AsyncSession, *, now: datetime | None = None) -> bool:
    """Пора ли выплеснуть буфер ачивок.

    Правила:
    * ночь — только сбор (вне живых часов не выплёскиваем);
    * утренний слот — весь ночной «урожай» уходит одной сводкой;
    * днём — не чаще `interval_hours` и только если пул не пуст;
    * не перебиваем живой флуд и не столкновимся с критическим слотом (расписание).
    """
    from app.services.game import activity

    moment = now or datetime.now(timezone.utc)
    count = await pool_pending_count(session)
    if count == 0:
        return False
    if await activity.check_window(session, now=moment) != activity.OK:
        return False
    gap = await get_achievements_pool_gap_minutes(session)
    if in_reserved_gap(moment, gap_minutes=gap):
        return False
    local_hour = (moment.astimezone(timezone.utc).hour + ACTIVITY_TZ_OFFSET_HOURS) % 24
    # Утренний слот забирает весь ночной «урожай» даже из одной ачивки.
    if local_hour == await get_achievements_pool_morning_hour(session):
        return True
    # Днём не мельчим: ждём либо накопления порога, либо шага расписания.
    if count < await get_achievements_pool_min_items(session):
        return False
    raw = await get_achievements_pool_last_flush(session)
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    interval = await get_achievements_pool_interval_hours(session)
    return moment - last >= timedelta(hours=interval)


async def flush_achievements(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Выплеснуть буфер ачивок одной компактной сводкой (или несколькими кусками).

    Возвращает число отправленных записей; 0 — нечего или Telegram не принял
    (тогда записи остаются в буфере до следующего окна).
    """
    moment = now or datetime.now(timezone.utc)
    rows = await pending_entries(session, kinds=(KIND_ACHIEVEMENT_POOL,))
    if not rows:
        return 0
    names: dict[int | None, str] = {}
    groups: list[dict] = []
    index: dict[int | None, dict] = {}
    for row in rows:
        uid = row.subject_user_id
        if uid not in names:
            user = await session.get(User, uid) if uid is not None else None
            names[uid] = user.display_name if user is not None else "Участник"
        group = index.get(uid)
        if group is None:
            group = {"name": names[uid], "lines": []}
            index[uid] = group
            groups.append(group)
        group["lines"].append(row.text)
    interval = await get_achievements_pool_interval_hours(session)
    text = build_achievements_digest(groups, interval_hours=interval)
    markup = await _achievements_markup()
    chats = {row.chat_id for row in rows}
    target = chats.pop() if len(chats) == 1 else None
    sent_any = False
    for chunk in chunk_digest(text):
        ok = await send_now(
            chunk, chat_id=target, reply_markup=markup if not sent_any else None
        )
        if not ok:
            return 0
        sent_any = True
    for row in rows:
        row.sent_at = moment
    await session.commit()
    await set_achievements_pool_last_flush(session, moment.isoformat())
    log.info("game.achievements_flushed", entries=len(rows))
    return len(rows)


async def run_achievements_digest_job(now: datetime | None = None) -> int:
    """Job планировщика: если буфер не пуст и «пора» — выплеснуть сводку ачивок.

    Job тикает часто (раз в 15 мин), а решение принимает сам: так правки частоты
    и утреннего слота в админке работают без пересоздания job'а.
    """
    from app.db.base import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as session:
        if not await achievements_digest_due(session, now=now):
            return 0
        return await flush_achievements(session, now=now)
