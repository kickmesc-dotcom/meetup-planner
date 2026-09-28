"""GHG10: ФАСАД НАЧИСЛЕНИЯ — единственная точка входа для событий бота.

Правило проекта (Э2 задания): **везде, где появляется опыт или ачивка, код зовёт
только функции этого модуля**, а не `xp.award` / `achievements.grant` напрямую.
Три причины:

1. **Рубильник.** Каждая функция начинается с `await is_game_enabled(session)` и
   при выключенной игре выходит молча — без начислений, ачивок и анонсов. Так
   забыть проверку в новом месте вызова невозможно.
2. **Событие = его XP + его ачивки.** «Стал лохом» одновременно даёт 10 опыта и
   двигает «С почином» — держать это в одном месте дешевле, чем в четырёх.
3. **Игра не может ломать бота.** Каждый вызов обёрнут `_guarded`: исключение
   любого рода логируется как `game.award_failed`, транзакция откатывается, а
   вызывающий код продолжает работу. Поэтому в местах вызова достаточно одной
   строки и НЕ нужен свой try/except.

Единственное требование к вызывающему коду: звать эти функции ПОСЛЕ собственного
commit'а (исключение — `message()`, которая пишет и коммитит сама). Тогда откат
внутри `_guarded` не может потерять чужие несохранённые данные.

Исключение из правила 1: ачивка начисляет себе опыт сама внутри
`achievements.grant` (событие «получил ачивку» = 50 XP), иначе каждая выдача
давала бы две копии.
"""
from __future__ import annotations

import functools
from datetime import datetime, time, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AvailabilityRange, ChatActivityDaily, User
from app.services.game import achievements, xp
from app.services.game.achievements import STATUS_FREE
from app.services.game.config import (
    EV_ACHIEVEMENT,
    EV_AVAILABILITY,
    EV_BECAME_CHUKHAN,
    EV_BECAME_LOSER,
    EV_BIRTHDAY,
    EV_HOLIDAY,
    EV_MEETING,
    EV_MESSAGE,
    EV_QUOTE,
)
from app.services.game.flags import is_game_enabled

log = structlog.get_logger()


def _guarded(event: str):
    """Обёртка «игра не ломает бота».

    Ловит любое исключение, откатывает транзакцию (сессия остаётся рабочей —
    важно, например, для чухан-поста, которому после игры ещё слать опрос) и
    возвращает None вместо результата.
    """

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(session: AsyncSession, *args, **kwargs):
            try:
                return await fn(session, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                # ⚠️ `game_event`, а не `event`: `event` — зарезервированный ключ
                # structlog (само сообщение), и передача его kwarg'ом бросает
                # TypeError прямо внутри обработчика ошибки.
                log.warning("game.award_failed", game_event=event, error=str(exc))
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001 — сессия уже мертва, не наша беда
                    pass
                return None

        return wrapper

    return decorator


def _week_bounds(at: datetime | None = None) -> tuple[datetime, datetime]:
    """Границы текущей ISO-недели (UTC, понедельник 00:00) — как в `xp.window_key`."""
    moment = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    monday = (moment - timedelta(days=moment.weekday())).date()
    start = datetime.combine(monday, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


async def _enabled(session: AsyncSession) -> bool:
    return await is_game_enabled(session)


async def user_id_for_tg(session: AsyncSession, telegram_id: int) -> int | None:
    """PK юзера по TG-id. Нужно там, где источник события хранит TG-id
    (номинации игр) — конвертация делается один раз здесь, а не в трекерах."""
    return await session.scalar(select(User.id).where(User.telegram_id == telegram_id))


# --------------------------------------------------------------------------
# Сообщения в чате (2.1)
# --------------------------------------------------------------------------


async def _bump_activity(
    session: AsyncSession, user_id: int, at: datetime | None = None
) -> None:
    """Durable счётчик сообщений по дням (`chat_activity_daily`)."""
    day = xp.utc_day(at)
    row = await session.get(ChatActivityDaily, (user_id, day))
    if row is None:
        session.add(ChatActivityDaily(user_id=user_id, day=day, messages=1))
    else:
        row.messages += 1


@_guarded(EV_MESSAGE)
async def message(
    session: AsyncSession, user_id: int, *, at: datetime | None = None
) -> None:
    """Сообщение в общем чате: +1 XP и +1 к недельному счётчику активности.

    Оба изменения — в ОДНОЙ транзакции (один commit на сообщение): это самый
    горячий путь игры, поэтому не плодим лишние round-trip'ы к Neon.
    """
    if not await _enabled(session):
        return
    await xp.award(session, user_id, EV_MESSAGE, at=at, commit=False)
    await _bump_activity(session, user_id, at)
    await session.commit()


@_guarded(EV_QUOTE)
async def quote(session: AsyncSession, user_id: int, *, at: datetime | None = None) -> None:
    """Бот вкинул цитату от имени юзера: +1 XP (2.6)."""
    if not await _enabled(session):
        return
    await xp.award(session, user_id, EV_QUOTE, at=at)


# --------------------------------------------------------------------------
# Звания (2.2, 2.3)
# --------------------------------------------------------------------------


@_guarded(EV_BECAME_LOSER)
async def loser(
    session: AsyncSession,
    *,
    loser_id: int,
    roller_id: int,
    source: str,
    roll_id: int | None = None,
    at: datetime | None = None,
) -> None:
    """Выпал лох. `source='duel'` — развлекательный прокрут: опыта не даёт
    (см. `achievements.on_loser`), но трекеры «Искателя истины»/«Самострела» — да."""
    if not await _enabled(session):
        return
    if source != "duel":
        # Дискриминатор = id ролла: ретрай не начислит второй раз за того же лоха.
        await xp.award(
            session, loser_id, EV_BECAME_LOSER, at=at, discriminator=roll_id
        )
    await achievements.on_loser(
        session, loser_id=loser_id, roller_id=roller_id, source=source
    )


@_guarded(EV_BECAME_CHUKHAN)
async def chukhan(
    session: AsyncSession,
    user_id: int,
    *,
    week_start: datetime | None = None,
    at: datetime | None = None,
) -> None:
    """Стал чуханом недели: +100 XP (раз на неделю — по дискриминатору недели)."""
    if not await _enabled(session):
        return
    disc = week_start.isoformat() if week_start is not None else None
    await xp.award(
        session, user_id, EV_BECAME_CHUKHAN, at=at or week_start, discriminator=disc
    )
    await achievements.on_chukhan(session, user_id)


# --------------------------------------------------------------------------
# Календарь (2.5)
# --------------------------------------------------------------------------


@_guarded(EV_AVAILABILITY)
async def availability(
    session: AsyncSession, user_id: int, *, at: datetime | None = None
) -> None:
    """Разметил свободные дни. Опыт — раз в неделю и только если размечен день
    ТЕКУЩЕЙ недели (иначе «разметил 2027 год» давало бы +10 XP каждую неделю)."""
    if not await _enabled(session):
        return
    start, end = _week_bounds(at)
    touched = await session.scalar(
        select(AvailabilityRange.id)
        .where(
            AvailabilityRange.user_id == user_id,
            AvailabilityRange.status == STATUS_FREE,
            AvailabilityRange.starts_at < end,
            AvailabilityRange.ends_at > start,
        )
        .limit(1)
    )
    if touched is not None:
        await xp.award(session, user_id, EV_AVAILABILITY, at=at)
    await achievements.on_availability(session, user_id)


# --------------------------------------------------------------------------
# ДР, праздники, встречи (2.7, 2.8, 2.9)
# --------------------------------------------------------------------------


@_guarded(EV_BIRTHDAY)
async def birthday(
    session: AsyncSession, user_id: int, *, at: datetime | None = None
) -> None:
    """ДР юзера: +100 XP (раз в год)."""
    if not await _enabled(session):
        return
    await xp.award(session, user_id, EV_BIRTHDAY, at=at)


@_guarded(EV_HOLIDAY)
async def holiday(
    session: AsyncSession,
    user_ids: list[int],
    *,
    holiday_id: int | None = None,
    at: datetime | None = None,
) -> int:
    """Праздник: +50 XP всем.

    Дискриминатор = id праздника (в году их несколько, поэтому «раз в год» без
    дискриминатора съело бы второй праздник). Возвращает, СКОЛЬКО начислений
    прошло именно сейчас — по этому числу решается, оглашать ли праздник
    (повторный прогон job'а в тот же день молчит).
    """
    if not await _enabled(session):
        return 0
    granted = 0
    for uid in user_ids:
        res = await xp.award(
            session, uid, EV_HOLIDAY, at=at, discriminator=holiday_id
        )
        if res.awarded:
            granted += 1
    return granted


@_guarded(EV_MEETING)
async def meeting(
    session: AsyncSession,
    user_id: int,
    meeting_id: int | None = None,
    *,
    at: datetime | None = None,
) -> None:
    """Инициировал встречу: +50 XP."""
    if not await _enabled(session):
        return
    await xp.award(session, user_id, EV_MEETING, at=at, discriminator=meeting_id)


# --------------------------------------------------------------------------
# Ачивки-события, у которых нет собственного XP (Э4/Э6/Э7/Э11)
# --------------------------------------------------------------------------


@_guarded("poll_created")
async def poll_created(session: AsyncSession, user_id: int) -> None:
    """Создан опрос → «Агент ВЦИОМ-а» после третьего (данные — из `polls`)."""
    if not await _enabled(session):
        return
    await achievements.on_poll_created(session, user_id)


@_guarded("nomination")
async def nomination(session: AsyncSession, user_id: int) -> None:
    """Номинирована игра → «Номинальный номинал» после третьей."""
    if not await _enabled(session):
        return
    await achievements.on_nomination(session, user_id)


@_guarded("nomination")
async def nomination_by_tg(session: AsyncSession, telegram_id: int) -> None:
    """То же, но источник хранит TG-id (см. `services/games.py`)."""
    if not await _enabled(session):
        return
    uid = await user_id_for_tg(session, telegram_id)
    if uid is None:
        return
    await achievements.on_nomination(session, int(uid))


@_guarded("game_winner")
async def game_winner(session: AsyncSession, user_id: int) -> None:
    """Номинированная юзером игра победила → «Номинатор»."""
    if not await _enabled(session):
        return
    await achievements.on_game_winner(session, user_id)


@_guarded("game_winner")
async def game_winner_by_tg(session: AsyncSession, telegram_id: int) -> None:
    if not await _enabled(session):
        return
    uid = await user_id_for_tg(session, telegram_id)
    if uid is None:
        return
    await achievements.on_game_winner(session, int(uid))


@_guarded("chukhan_reroll")
async def chukhan_reroll(session: AsyncSession, user_id: int) -> None:
    """Инициирован реролл чухана → «Переписал историю»."""
    if not await _enabled(session):
        return
    await achievements.on_chukhan_reroll(session, user_id)


@_guarded("bot_reply")
async def bot_reply(session: AsyncSession, user_id: int) -> None:
    """Ответил боту реплаем/упоминанием → счётчик «Укротителя паст»."""
    if not await _enabled(session):
        return
    await achievements.on_bot_reply(session, user_id)


@_guarded("bot_reply")
async def bot_reply_by_tg(session: AsyncSession, telegram_id: int) -> None:
    """То же, но вызывающий код оперирует TG-id (хендлеры aiogram)."""
    if not await _enabled(session):
        return
    uid = await user_id_for_tg(session, telegram_id)
    if uid is None:
        return
    await achievements.on_bot_reply(session, int(uid))


@_guarded("meme_reactions")
async def meme_reactions(session: AsyncSession, user_id: int) -> None:
    """Э7: пост с мемом собрал реакции (зовёт телеметрия мем-ачивок)."""
    if not await _enabled(session):
        return
    await achievements.on_meme_reactions(session, user_id)


@_guarded("dead_post")
async def dead_post(session: AsyncSession, user_id: int) -> None:
    """Э7: 12 часов тишины после поста."""
    if not await _enabled(session):
        return
    await achievements.on_dead_post(session, user_id)


@_guarded("donation_sent")
async def donation_sent(
    session: AsyncSession,
    donor_id: int,
    *,
    recipients_this_year: int,
    live_participants: int,
) -> None:
    """Э11: донат экспы (сам перевод делает модуль донатов)."""
    if not await _enabled(session):
        return
    await achievements.on_donation_sent(
        session,
        donor_id,
        recipients_this_year=recipients_this_year,
        live_participants=live_participants,
    )


@_guarded("week_activity")
async def week_activity(
    session: AsyncSession,
    *,
    most_active_id: int | None,
    least_active_id: int | None,
    week_key: str | None = None,
) -> None:
    """Э6: итог недели по активности (зовёт недельный job).

    `week_key` — ISO-неделя (`2026-W39`): с ней вызов идемпотентен, поэтому
    повторный прогон job'а за ту же неделю ничего не выдает второй раз.
    """
    if not await _enabled(session):
        return
    await achievements.on_week_activity(
        session,
        most_active_id=most_active_id,
        least_active_id=least_active_id,
        week_key=week_key,
    )


@_guarded(EV_ACHIEVEMENT)
async def achievement(session: AsyncSession, user_id: int, code: str) -> None:
    """Выдать конкретную ачивку (админка/отладка) — тоже за рубильником."""
    if not await _enabled(session):
        return
    await achievements.grant(session, user_id, code)


# Коды событий, которые модуль вообще может начислить (для админки/тестов).
ALL_EVENTS = (
    EV_MESSAGE,
    EV_QUOTE,
    EV_BECAME_LOSER,
    EV_BECAME_CHUKHAN,
    EV_ACHIEVEMENT,
    EV_AVAILABILITY,
    EV_BIRTHDAY,
    EV_HOLIDAY,
    EV_MEETING,
)
