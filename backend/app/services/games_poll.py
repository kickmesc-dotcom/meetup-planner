"""GHG6 E6 — голосования по играм: «Во что сыграем» и follow-up «Когда играем».

Переиспользуем существующую инфраструктуру `polls`/`poll_options`/`poll_votes`,
расширенную полями `polls.kind` ('game_choice' | 'game_when') и
`polls.game_nomination_id` (для game_when — id игры-победителя, чтобы знать,
к какой игре привязать создаваемый Meeting).

Связь между `PollOption` и `GameNomination` для game_choice — по `label`
(имя игры). Активные номинации уже дедуплицированы по имени
(case-insensitive) на уровне `services/games.py`, поэтому коллизий быть не
может в пределах одного голосования.

`starts_at` / `ends_at` у `PollOption` для game-полов — заглушка `now()`:
эти поля семантически про meetup-time-варианты, для игр они не используются.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    GameNomination,
    Meeting,
    Poll,
    PollOption,
    PollVote,
    User,
)

log = structlog.get_logger()

POLL_KIND_GAME_CHOICE = "game_choice"
POLL_KIND_GAME_WHEN = "game_when"
MEETING_TAG_GAME = "game"

# GHG6 hotfix: при «полумёртвом» прокси `bot.send_poll` зависает до сетевого
# таймаута aiohttp (~30с) и валит весь ASGI-запрос с asyncio.CancelledError.
# Ограничиваем 8с — UX-обратка фронта (alert после ответа) дольше не ждёт.
_POLL_SEND_TIMEOUT = 8.0


class GamesPollSendFailed(Exception):
    """Не удалось отправить TG-полл — Poll в БД НЕ создан.

    Бросается из `create_game_choice_poll`/`create_game_when_poll`, когда
    `bot.send_poll` падает по таймауту/network/api-error. HTTP-роут ловит и
    возвращает 503 — фронт показывает понятную ошибку, висячих записей в БД
    не остаётся.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

_RU_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


async def _active_nominations_by_ids(
    session: AsyncSession, nomination_ids: list[int] | None
) -> list[GameNomination]:
    q = select(GameNomination).where(GameNomination.removed_at.is_(None))
    if nomination_ids:
        q = q.where(GameNomination.id.in_(nomination_ids))
    q = q.order_by(GameNomination.added_at.asc())
    rows = await session.scalars(q)
    return list(rows.all())


async def create_game_choice_poll(
    session: AsyncSession,
    bot: Bot,
    *,
    chat_id: int,
    created_by: User,
    timeout_hours: int,
    nomination_ids: list[int] | None,
    follow_up_when: bool,
    pin: bool = False,
) -> Poll:
    """Запустить TG-полл «Во что сыграем» и сохранить запись Poll(kind='game_choice').

    Telegram-полл: anonymous=False, single answer, open_period.
    `follow_up_when` сохраняем в первой ячейке `PollOption.label`-… нет,
    отдельного поля нет — кладём в payload AdminConfig? Нет, проще держать
    флаг прямо на Poll. Расширять схему не хочу, поэтому пишем в
    `Poll.question` префикс `[+when]` для опознания (читается только в
    handler закрытия). Это ad-hoc, но локально и не утечёт в UI: чат-вопрос
    отображается из Telegram-полла, а не из этого поля.

    Возвращает уже-залитый в БД Poll с проставленным `tg_poll_id`/`tg_message_id`.
    """
    nominations = await _active_nominations_by_ids(session, nomination_ids)
    if len(nominations) < 2:
        raise ValueError("not_enough_nominations:need_2_or_more")
    if len(nominations) > 10:
        # Telegram-poll-limit, выше не пускаем.
        raise ValueError("too_many_options:max_10")

    labels = [n.name for n in nominations]
    question = "🎮 Во что сыграем?"
    # Префикс для опознания follow_up в handler закрытия — без расширения схемы.
    stored_question = ("[+when] " + question) if follow_up_when else question

    # GHG6 hotfix: send_poll ДО session.add — если упадёт по таймауту прокси,
    # в БД не должно остаться «висячей» Poll-записи без TG-сообщения.
    try:
        msg = await asyncio.wait_for(
            bot.send_poll(
                chat_id=chat_id,
                question=question,
                options=labels,
                is_anonymous=False,
                allows_multiple_answers=False,
                open_period=timeout_hours * 3600,
            ),
            timeout=_POLL_SEND_TIMEOUT,
        )
    except (
        TelegramRetryAfter,
        TelegramForbiddenError,
        TelegramNetworkError,
        TelegramAPIError,
        asyncio.TimeoutError,
    ) as exc:
        log.warning(
            "games_poll.choice_send_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise GamesPollSendFailed(type(exc).__name__) from exc

    closes_at = datetime.now(timezone.utc) + timedelta(hours=timeout_hours)
    poll = Poll(
        created_by=created_by.id,
        question=stored_question,
        closes_at=closes_at,
        tg_message_id=msg.message_id,
        tg_poll_id=msg.poll.id if msg.poll else None,
        kind=POLL_KIND_GAME_CHOICE,
    )
    session.add(poll)
    await session.flush()

    now = datetime.now(timezone.utc)
    for nom in nominations:
        session.add(
            PollOption(
                poll_id=poll.id,
                starts_at=now,
                ends_at=now,
                label=nom.name,
            )
        )
    await session.commit()
    await session.refresh(poll)
    log.info(
        "games_poll.choice_created",
        poll_id=poll.id,
        options=len(nominations),
        follow_up=follow_up_when,
    )

    # GHG6 G2: пин опционально, ошибки глотает помощник.
    # `follow_up_when` префикс уже в question — флаг pin кодируем там же,
    # чтобы handle_game_choice_closed знал, нужно ли пинить follow-up-полл.
    if pin:
        from app.bot.utils.pinning import pin_message_safely
        await pin_message_safely(bot, chat_id=chat_id, message_id=msg.message_id)
        # Помечаем choice-полл, чтобы при auto-создании when-полла унаследовать pin.
        # Префикс [+pin] идёт ПЕРЕД [+when], если оба есть.
        new_question = "[+pin] " + poll.question
        poll.question = new_question
        await session.commit()
        await session.refresh(poll)

    return poll


def _default_when_options(today: date) -> list[date]:
    """Три ближайшие даты: today/tomorrow/+2. Без time-компонента — date-only."""
    return [today, today + timedelta(days=1), today + timedelta(days=2)]


def _fmt_date_label(d: date) -> str:
    return f"{_RU_DAYS[d.weekday()]} {d.strftime('%d.%m')}"


async def create_game_when_poll(
    session: AsyncSession,
    bot: Bot,
    *,
    chat_id: int,
    created_by_user_id: int,
    nomination: GameNomination,
    timeout_hours: int,
    dates: list[date] | None = None,
    pin: bool = False,
) -> Poll:
    """Follow-up «Когда играем» — короткий полл на 3 даты по умолчанию.

    single answer, non-anonymous, open_period. На каждый PollOption кладём
    starts_at = соответствующая дата (00:00 UTC) — это и есть «время»
    встречи (без часа). При закрытии победитель → Meeting.
    """
    if dates is None:
        # today в UTC — достаточно для группы в одном TZ; уточнение времени —
        # вручную после создания встречи.
        dates = _default_when_options(datetime.now(timezone.utc).date())
    if len(dates) < 2:
        raise ValueError("when_poll_needs_2_dates")

    labels = [_fmt_date_label(d) for d in dates]
    question = f"📅 Когда играем в «{nomination.name}»?"
    try:
        msg = await asyncio.wait_for(
            bot.send_poll(
                chat_id=chat_id,
                question=question,
                options=labels,
                is_anonymous=False,
                allows_multiple_answers=False,
                open_period=timeout_hours * 3600,
            ),
            timeout=_POLL_SEND_TIMEOUT,
        )
    except (
        TelegramRetryAfter,
        TelegramForbiddenError,
        TelegramNetworkError,
        TelegramAPIError,
        asyncio.TimeoutError,
    ) as exc:
        log.warning(
            "games_poll.when_send_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            nomination_id=nomination.id,
        )
        raise GamesPollSendFailed(type(exc).__name__) from exc

    closes_at = datetime.now(timezone.utc) + timedelta(hours=timeout_hours)
    poll = Poll(
        created_by=created_by_user_id,
        question=question,
        closes_at=closes_at,
        tg_message_id=msg.message_id,
        tg_poll_id=msg.poll.id if msg.poll else None,
        kind=POLL_KIND_GAME_WHEN,
        game_nomination_id=nomination.id,
    )
    session.add(poll)
    await session.flush()

    for d, label in zip(dates, labels, strict=True):
        starts_at = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
        session.add(
            PollOption(
                poll_id=poll.id,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=24),
                label=label,
            )
        )
    await session.commit()
    await session.refresh(poll)
    log.info(
        "games_poll.when_created",
        poll_id=poll.id,
        nomination_id=nomination.id,
        dates=[d.isoformat() for d in dates],
    )

    # GHG6 G2: пин опционально.
    if pin:
        from app.bot.utils.pinning import pin_message_safely
        await pin_message_safely(bot, chat_id=chat_id, message_id=msg.message_id)

    return poll


async def _option_vote_counts(
    session: AsyncSession, poll_id: int
) -> dict[int, int]:
    """Сколько голосов за каждый PollOption. Чисто по нашей БД (голоса
    приходят через `poll_answer` → `record_poll_answer`)."""
    rows = await session.execute(
        select(PollVote.poll_option_id, func.count(PollVote.user_id))
        .join(PollOption, PollOption.id == PollVote.poll_option_id)
        .where(PollOption.poll_id == poll_id)
        .group_by(PollVote.poll_option_id)
    )
    return {pid: int(cnt) for pid, cnt in rows.all()}


async def pick_winner_option(
    session: AsyncSession, poll_id: int
) -> PollOption | None:
    """Победитель: опция с max голосов. При ничьей берётся ранее добавленная
    (стабильный порядок по id ASC). При 0 голосах — `None`."""
    counts = await _option_vote_counts(session, poll_id)
    if not counts:
        return None
    options = list(
        (
            await session.scalars(
                select(PollOption)
                .where(PollOption.poll_id == poll_id)
                .order_by(PollOption.id.asc())
            )
        ).all()
    )
    if not options:
        return None
    # max по (votes, -id) — больше голосов, при ничьей раньше созданная опция.
    best = max(options, key=lambda o: (counts.get(o.id, 0), -o.id))
    if counts.get(best.id, 0) == 0:
        return None
    return best


async def handle_game_choice_closed(
    session: AsyncSession, bot: Bot, *, poll: Poll, chat_id: int
) -> Poll | None:
    """Закрылся `game_choice`-полл. Объявляем победителя в чат и (если
    `follow_up_when` был флагом — закодирован префиксом в question)
    запускаем `game_when`-голосование.

    Возвращает созданный follow-up Poll или None.
    """
    winner_opt = await pick_winner_option(session, poll.id)
    if winner_opt is None:
        try:
            await bot.send_message(
                chat_id, "🎮 Голосование закрылось без голосов — играем что хотим."
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("games_poll.announce_no_votes_failed", error=str(exc))
        return None

    nomination = await session.scalar(
        select(GameNomination).where(
            func.lower(GameNomination.name) == winner_opt.label.lower(),
            GameNomination.removed_at.is_(None),
        )
    )

    try:
        await bot.send_message(
            chat_id,
            f"🎮 Победила <b>{winner_opt.label}</b>!",
            parse_mode="HTML",
            reply_to_message_id=poll.tg_message_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("games_poll.announce_winner_failed", error=str(exc))

    # GHG6 G2: префиксы [+pin] и [+when] в question — флаги choice-полла.
    # Порядок: [+pin] идёт перед [+when], если оба есть.
    q = poll.question
    pinned = "[+pin]" in q
    follow_up = "[+when]" in q
    if not follow_up or nomination is None:
        return None

    # Используем тот же timeout, что и у choice — простая эвристика.
    timeout_hours = 24
    if poll.closes_at and poll.created_at:
        delta = poll.closes_at - poll.created_at
        timeout_hours = max(1, min(72, int(delta.total_seconds() // 3600)))
    try:
        when_poll = await create_game_when_poll(
            session,
            bot,
            chat_id=chat_id,
            created_by_user_id=poll.created_by,
            nomination=nomination,
            timeout_hours=timeout_hours,
            pin=pinned,
        )
    except GamesPollSendFailed as exc:
        # Зовётся из bot-handler `poll_answer.py` (не HTTP) — глотаем,
        # follow-up не создаётся, choice-победитель уже объявлен в чат.
        log.warning("games_poll.followup_send_failed", reason=exc.reason)
        return None
    return when_poll


async def handle_game_when_closed(
    session: AsyncSession, bot: Bot, *, poll: Poll, chat_id: int
) -> Meeting | None:
    """Закрылся `game_when`-полл. Победившая дата → Meeting с tag='game'."""
    winner_opt = await pick_winner_option(session, poll.id)
    if winner_opt is None:
        try:
            await bot.send_message(
                chat_id, "📅 По дате не сошлись — без записи в календарь."
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("games_poll.when_no_votes_failed", error=str(exc))
        return None

    nomination = None
    if poll.game_nomination_id is not None:
        nomination = await session.get(GameNomination, poll.game_nomination_id)
    title = (nomination.name if nomination else "Игра") + " 🎮"

    meeting = Meeting(
        created_by=poll.created_by,
        title=title,
        starts_at=winner_opt.starts_at,
        ends_at=winner_opt.ends_at,
        status="confirmed",
        auto_picked=False,
        tag=MEETING_TAG_GAME,
    )
    session.add(meeting)
    await session.commit()
    await session.refresh(meeting)

    log.info(
        "games_poll.meeting_created",
        meeting_id=meeting.id,
        nomination_id=poll.game_nomination_id,
        starts_at=winner_opt.starts_at.isoformat(),
    )

    try:
        await bot.send_message(
            chat_id,
            f"📅 Играем <b>{winner_opt.label}</b> — добавил в календарь.",
            parse_mode="HTML",
            reply_to_message_id=poll.tg_message_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("games_poll.when_announce_failed", error=str(exc))

    return meeting
