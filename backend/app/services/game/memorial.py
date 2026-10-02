"""GHG10 Э13: автоматические «поминальные» сообщения.

Задание дословно:

     Если человек давно ничего не писал:
         Сегодня ровно 3 недели с последнего сообщения Митяна.
         Мы почти привыкли.
     А когда возвращается:
         ⚠️ ОН ЗДЕСЬ
         Сервер подтверждает личность.

Откуда берём «давно»: `chat_messages` для этого не годится (чистится через 7
дней, а речь про три недели). Единственный durable-след человека в чате —
агрегат `chat_activity_daily` («сообщение = +1 к дневному счётчику»), поэтому
тишина считается по последнему дню с активностью. Побочный эффект, который
честно назван в докстринге: считаем только с момента появления счётчика
(выкатка GHG10), поэтому у человека без единой строки активности «последнего
сообщения» просто нет и поминовения не будет.

Состояние поминовения — строка `game_journal` с `kind='memorial'` и
`subject_user_id`: пока `resolved_at IS NULL`, человек «в розыске». Именно
поэтому возвращение не требует ни новой таблицы, ни фонового сканирования —
это один индексный `SELECT` в горячем пути сообщения.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatActivityDaily, GameJournalEntry, User
from app.services.admin_config import (
    get_game_memorial_enabled,
    get_game_memorial_repeat_days,
    get_game_memorial_silence_days,
)
from app.services.game import activity, journal
from app.services.game.config import MEMORIAL_RETURN_TEXT

log = structlog.get_logger()

WEEK_DAYS = 7


def plural(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение по числу. Чистая функция (тесты)."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def memorial_text(name: str, *, silent_days: int) -> str:
    """Текст поминовения. Чистая функция — тестируется без БД."""
    weeks = max(1, silent_days // WEEK_DAYS)
    word = plural(weeks, "неделя", "недели", "недель")
    return (
        f"🕯 Сегодня ровно {weeks} {word} с последнего сообщения <b>{name}</b>.\n\n"
        "Мы почти привыкли."
    )


def silence_days(*, last_day: date, today: date) -> int:
    """Сколько дней человек молчит (по последнему дню с активностью)."""
    return max(0, (today - last_day).days)


async def last_activity_days(session: AsyncSession) -> dict[int, date]:
    """user_id → последний день, когда он что-то писал."""
    rows = await session.execute(
        select(ChatActivityDaily.user_id, func.max(ChatActivityDaily.day)).group_by(
            ChatActivityDaily.user_id
        )
    )
    return {int(uid): day for uid, day in rows.all()}


async def open_memorial(
    session: AsyncSession, user_id: int
) -> GameJournalEntry | None:
    """Открытое (не закрытое возвращением) поминовение человека, если есть."""
    return await session.scalar(
        select(GameJournalEntry)
        .where(
            GameJournalEntry.kind == journal.KIND_MEMORIAL,
            GameJournalEntry.subject_user_id == user_id,
            GameJournalEntry.resolved_at.is_(None),
        )
        .order_by(GameJournalEntry.created_at.desc())
        .limit(1)
    )


async def run_memorial_job(*, today: date | None = None, now: datetime | None = None) -> int:
    """Ежедневный обход: помянуть тех, кто молчит дольше порога.

    Поминовение повторяется не чаще `game.memorial.repeat_days`, чтобы долгое
    молчание не превращалось в ежедневную колонку «а помним ли мы Митяна».
    Возвращает число отправленных сообщений.
    """
    from app.db.base import get_sessionmaker

    moment = now or datetime.now(timezone.utc)
    day = today or moment.date()
    sm = get_sessionmaker()
    posted = 0
    async with sm() as session:
        if not await get_game_memorial_enabled(session):
            return 0
        # Э18: единый режим активностей — поминование не лезет ночью и не
        # перебивает живое обсуждение. Пропуск не теряется: следующее окно
        # (job тикает ежедневно) догонит.
        if await activity.check_window(session, now=moment) != activity.OK:
            return 0
        threshold = await get_game_memorial_silence_days(session)
        repeat_days = await get_game_memorial_repeat_days(session)
        activity = await last_activity_days(session)
        if not activity:
            return 0
        users = {
            int(u.id): u.display_name
            for u in (await session.scalars(select(User))).all()
        }
        for user_id, last_day in activity.items():
            if user_id not in users:
                continue
            silent = silence_days(last_day=last_day, today=day)
            if silent < threshold:
                continue
            entry = await open_memorial(session, user_id)
            if entry is not None and entry.repeat_after is not None:
                if moment < entry.repeat_after:
                    continue
            text = memorial_text(users[user_id], silent_days=silent)
            if entry is None:
                entry = GameJournalEntry(
                    kind=journal.KIND_MEMORIAL,
                    text=text,
                    subject_user_id=user_id,
                )
                session.add(entry)
            else:
                entry.text = text
            entry.repeat_after = moment + timedelta(days=repeat_days)
            # Поминовение уходит в чат сразу: оно и так редкое, а ждать сводки
            # ему незачем (и в журнале оно не должно висеть как «непоказанное»).
            entry.sent_at = moment
            await session.commit()
            if await journal.send_now(text):
                posted += 1
        if posted:
            log.info("game.memorials_posted", count=posted)
    return posted


async def note_return(
    session: AsyncSession, *, user_id: int, at: datetime | None = None
) -> bool:
    """Человек вернулся: закрыть поминовение и сказать «ОН ЗДЕСЬ».

    Дёргается из обработчика каждого сообщения, поэтому обязана быть дешёвой:
    один индексный `SELECT` по (subject_user_id, kind). Если открытого
    поминовения нет — выходим сразу и молчим.
    """
    entry = await open_memorial(session, user_id)
    if entry is None:
        return False
    entry.resolved_at = at or datetime.now(timezone.utc)
    await session.commit()
    await journal.send_now(MEMORIAL_RETURN_TEXT)
    log.info("game.memorial_returned", user_id=user_id)
    return True
