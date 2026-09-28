"""GHG10: движок ачивок — выдача, лист, анонс в общий чат и трекеры.

Разделение, как во всём игровом модуле:

* **Каталог** (что вообще существует) — `achievements_catalog.py`, чистые данные.
* **Этот модуль** — I/O: выдать ачивку, показать лист, анонсировать, посчитать
  счётчики по существующим таблицам.

Ключевое правило: **счётчики не дублируют данные**. «Стал лохом N раз» считается
по `loser_rolls`, «стал чуханом» — по `weekly_chukhan`, «создал 3 опроса» — по
`polls`, «инициировал реролл» — по `weekly_chukhan`. Собственная таблица счётчиков
(`achievement_counters`) нужна ТОЛЬКО там, где источника нет вообще (ответы боту,
посты с реакциями, мёртвые посты).

Рубильник: этот модуль НЕ проверяет `game.enabled` сам — это делает фасад
`awards.py`, единственная точка входа для событий. Прямой вызов `grant()` —
это уже отладочный/админский путь.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    AchievementCounter,
    AvailabilityRange,
    ChatActivityDaily,
    GameNomination,
    LoserRoll,
    Poll,
    User,
    UserAchievement,
    WeeklyChukhan,
    XpGrant,
)
from app.services.game import xp
from app.services.game.achievements_catalog import (
    SUPREME_CHUKHAN_CODE,
    SUPREME_CHUKHAN_TIER,
    SUPREME_CHUKHAN_TIER_BASE,
    Achievement,
    get,
    tiers_reached,
)
from app.services.game.config import EV_ACHIEVEMENT

log = structlog.get_logger()

# Собственные счётчики (см. докстринг модуля). Код трекера ≠ код ачивки там, где
# трекер обслуживает несколько ачивок (например успешные посты → `successful_success`).
COUNTER_WORM_TAMER = "worm_tamer"
COUNTER_SUCCESS = "successful_success"
COUNTER_OPIUM = "opium_for_nobody"
# Недельные звания: «сколько раз уже был» источником не выводится (недельный job
# не пишет отдельной таблицы), поэтому тоже собственный счётчик.
COUNTER_MOUTHPIECE = "generation_mouthpiece"
COUNTER_READ_ONLY = "read_only"

# `availability_ranges.status`: 1 — свободен (см. `services/auto_pick.py`).
STATUS_FREE = 1

# «Информатор»: сколько дней вперёд нужно разметить.
INFORMANT_DAYS = 30
# «Безработный»: сколько недель подряд.
UNEMPLOYED_WEEKS = 4


# ==========================================================================
# Чтение
# ==========================================================================


async def has(session: AsyncSession, user_id: int, code: str) -> bool:
    """Есть ли уже эта ачивка у юзера."""
    row = await session.scalar(
        select(UserAchievement.id).where(
            UserAchievement.user_id == user_id, UserAchievement.code == code
        )
    )
    return row is not None


async def collected_codes(session: AsyncSession, user_id: int) -> set[str]:
    rows = await session.scalars(
        select(UserAchievement.code).where(UserAchievement.user_id == user_id)
    )
    return set(rows.all())


@dataclass(frozen=True)
class CollectedAchievement:
    """Собранная ачивка + когда. Для листа в профиле (Э5)."""

    achievement: Achievement
    unlocked_at: datetime


async def collected(session: AsyncSession, user_id: int) -> list[CollectedAchievement]:
    """Лист собранных ачивок, новые сверху. Мусорные коды (каталог переехал)
    молча выкидываем — иначе профиль падал бы на старых записях."""
    rows = (
        await session.scalars(
            select(UserAchievement)
            .where(UserAchievement.user_id == user_id)
            .order_by(UserAchievement.unlocked_at.desc())
        )
    ).all()
    out: list[CollectedAchievement] = []
    for row in rows:
        ach = get(row.code)
        if ach is not None:
            out.append(CollectedAchievement(ach, row.unlocked_at))
    return out


async def count_for_user(session: AsyncSession, user_id: int) -> int:
    """Сколько ачивок собрано (для чарта обладателей ачивок, Э5.3)."""
    total = await session.scalar(
        select(func.count())
        .select_from(UserAchievement)
        .where(UserAchievement.user_id == user_id)
    )
    return int(total or 0)


async def leaderboard(session: AsyncSession) -> list[tuple[int, int]]:
    """Чарт обладателей ачивок: [(user_id, count)] по убыванию, без нулей.

    Один агрегатный SELECT — без N+1 (требование Э12.1).
    """
    rows = (
        await session.execute(
            select(UserAchievement.user_id, func.count())
            .group_by(UserAchievement.user_id)
            .order_by(func.count().desc())
        )
    ).all()
    return [(int(uid), int(cnt)) for uid, cnt in rows]


async def is_supreme_chukhan(session: AsyncSession, user_id: int) -> bool:
    """Носитель спец-ранга «Верховный чухан» (Э3.4: приоритетнее ранга за уровень)."""
    return await has(session, user_id, SUPREME_CHUKHAN_CODE)


async def progress(session: AsyncSession, user_id: int) -> dict[str, int]:
    """Накопленные счётчики для ачивок с прогрессом (для UI «3/10»).

    Ключи — БАЗОВЫЕ коды ачивок, чтобы фронт показывал прогресс прямо по коду
    из каталога. Где источника нет (разовые) — ключа нет.
    """
    return {
        "chin_up": await count_losers(session, user_id),
        "first_worm": await count_chukhan(session, user_id),
        "truth_seeker": await count_started_rolls(session, user_id),
        "vciom_agent": await count_polls(session, user_id),
        "nominal_nominal": await count_nominations(session, user_id),
        COUNTER_WORM_TAMER: await get_counter(session, user_id, COUNTER_WORM_TAMER),
        COUNTER_SUCCESS: await get_counter(session, user_id, COUNTER_SUCCESS),
        COUNTER_OPIUM: await get_counter(session, user_id, COUNTER_OPIUM),
        COUNTER_MOUTHPIECE: await get_counter(session, user_id, COUNTER_MOUTHPIECE),
        COUNTER_READ_ONLY: await get_counter(session, user_id, COUNTER_READ_ONLY),
    }


async def supreme_holders(session: AsyncSession) -> set[int]:
    """Кто носит спец-ранг «Верховный чухан» (для чарта рангов — один SELECT)."""
    rows = await session.scalars(
        select(UserAchievement.user_id).where(
            UserAchievement.code == SUPREME_CHUKHAN_CODE
        )
    )
    return {int(uid) for uid in rows.all()}


# ==========================================================================
# Счётчики
# ==========================================================================


async def get_counter(session: AsyncSession, user_id: int, code: str) -> int:
    row = await session.get(AchievementCounter, (user_id, code))
    return row.count if row else 0


async def bump_counter(
    session: AsyncSession, user_id: int, code: str, delta: int = 1
) -> int:
    """Увеличить собственный счётчик и вернуть новое значение.

    Одна строка на (user, code) — таблица не растёт на каждое сообщение.
    """
    row = await session.get(AchievementCounter, (user_id, code))
    if row is None:
        row = AchievementCounter(user_id=user_id, code=code, count=delta)
        session.add(row)
    else:
        row.count += delta
    await session.flush()
    return row.count


# ==========================================================================
# Выдача
# ==========================================================================


async def grant(
    session: AsyncSession, user_id: int, code: str, *, announce: bool = True
) -> Achievement | None:
    """Выдать ачивку. Уже есть → None (идемпотентно, «один раз на юзера»).

    Побочные эффекты: строка `user_achievements` + опыт (`achievement = 50`,
    переопределяется `points` самой ачивки) + анонс в общий чат.
    """
    ach = get(code)
    if ach is None:
        log.warning("game.achievement_unknown_code", code=code)
        return None
    if await has(session, user_id, code):
        return None
    session.add(UserAchievement(user_id=user_id, code=code))
    try:
        await session.flush()
    except IntegrityError:
        # Гонка (два трекера одновременно) — ачивка уже вручена, молча выходим.
        await session.rollback()
        return None

    await xp.award(session, user_id, EV_ACHIEVEMENT, points=ach.points)

    if announce:
        await announce_granted(session, user_id, [ach])
    return ach


def capstone_codes(base: str, count: int) -> list[str]:
    """Капстоун-ачивки, которые идут в комплекте с последним юбилеем.

    Задание: «за каждый из них будет повышаться внутренний ранг вплоть до ранга
    Верховный чухан». Ранг выдаётся отдельной записью каталога (`supreme_chukhan`)
    — так он виден в листе ачивок и участвует в чарте. Держим это правилом
    каталога, а не рекурсией внутри `grant` (иначе результат выдачи не виден
    вызывающему коду и не попадает в анонс).
    """
    if base == SUPREME_CHUKHAN_TIER_BASE and count >= SUPREME_CHUKHAN_TIER:
        return [SUPREME_CHUKHAN_CODE]
    return []


async def grant_many(
    session: AsyncSession, user_id: int, codes: list[str], *, announce: bool = True
) -> list[Achievement]:
    """Выдать пачку, вернуть только реально выданные."""
    out: list[Achievement] = []
    for code in codes:
        ach = await grant(session, user_id, code, announce=announce)
        if ach is not None:
            out.append(ach)
    return out


async def _grant_counter(
    session: AsyncSession, user_id: int, base: str, count: int, *, announce: bool = True
) -> list[Achievement]:
    """Выдать базовый тир (count ≥ 1) и все достигнутые юбилеи счётчика."""
    codes: list[str] = []
    if count >= 1:
        codes.append(base)
    codes.extend(tiers_reached(base, count))
    codes.extend(capstone_codes(base, count))
    if not codes:
        return []
    return await grant_many(session, user_id, codes, announce=announce)


async def _grant_threshold(
    session: AsyncSession,
    user_id: int,
    code: str,
    count: int,
    threshold: int,
    *,
    announce: bool = True,
) -> list[Achievement]:
    if count < threshold:
        return []
    ach = await grant(session, user_id, code, announce=announce)
    return [ach] if ach else []


# ==========================================================================
# Анонс в общий чат + ссылка «свои ачивки»
# ==========================================================================


def build_announcement(name: str, achs: list[Achievement]) -> str:
    """Текст анонса. Чистая функция — тестируется без сети и без БД."""
    lines: list[str] = []
    for ach in achs:
        head = f"{ach.icon} <b>{name}</b> получает ачивку «<b>{ach.title}</b>»"
        lines.append(head)
        if ach.description:
            lines.append(f"<i>{ach.description}</i>")
        lines.append(f"<i>+{ach.points} XP</i>")
    if len(achs) > 1:
        lines.insert(0, f"🏆 <b>{name}</b> разом забирает {len(achs)} ачивок:")
    return "\n".join(lines)


async def achievements_url(bot=None) -> str:
    """Ссылка на лист ачивок в мини-аппе.

    Идеальный вариант — deep link `t.me/<bot>?startapp=achievements`: TG откроет
    именно мини-апп, а фронт по `start_param` переключится на профиль. Если
    username бота недоступен (нет сети/бота) — отдаём прямой URL мини-аппа:
    кнопка остаётся рабочей, просто без автоперехода на нужный экран.
    """
    settings = get_settings()
    username: str | None = None
    if bot is not None:
        try:
            # aiogram кэширует ответ getMe в `bot._me` — берём его первым, чтобы
            # не ходить в сеть на каждом анонсе.
            me = getattr(bot, "_me", None)
            if me is None:
                maybe = getattr(bot, "me", None)
                if maybe is not None:
                    if callable(maybe):
                        maybe = maybe()
                    me = await maybe if inspect.isawaitable(maybe) else maybe
            username = getattr(me, "username", None) or None
        except Exception:  # noqa: BLE001 — ссылка не стоит падения анонса
            username = None
    if username:
        return f"https://t.me/{username}?startapp=achievements"
    return settings.mini_app_url


def _get_bot():
    """Ленивая добыча бота. Импорт внутри — иначе циклический (dispatcher → handlers)."""
    try:
        from app.bot.dispatcher import get_bot

        return get_bot()
    except Exception:  # noqa: BLE001
        return None


async def _link_markup(url: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏆 Свои ачивки", url=url)]
        ]
    )


async def announce_granted(
    session: AsyncSession, user_id: int, achs: list[Achievement]
) -> bool:
    """Анонс в общий чат. Best-effort: фейл TG не ломает начисление опыта."""
    if not achs:
        return False
    settings = get_settings()
    chat_id = settings.group_chat_id
    if not chat_id:
        return False
    user = await session.get(User, user_id)
    name = user.display_name if user else "Участник"
    text = build_announcement(name, achs)
    bot = _get_bot()
    try:
        url = await achievements_url(bot)
        markup = await _link_markup(url)
        if bot is None:
            return False
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
            disable_notification=False,
        )
        log.info(
            "game.achievement_announced",
            user_id=user_id,
            codes=[a.code for a in achs],
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("game.achievement_announce_failed", error=str(exc))
        return False


# ==========================================================================
# Трекеры: счётчики по существующим таблицам
# ==========================================================================

_OFFICIAL_SOURCE = LoserRoll.source != "duel"


async def count_losers(session: AsyncSession, user_id: int) -> int:
    """Сколько раз юзер был «лохом дня». Дубли (`source='duel'`) не считаем:
    это развлекательный прокрут, он не идёт даже в `loser_stats`."""
    total = await session.scalar(
        select(func.count())
        .select_from(LoserRoll)
        .where(LoserRoll.loser_user_id == user_id, _OFFICIAL_SOURCE)
    )
    return int(total or 0)


async def count_started_rolls(session: AsyncSession, user_id: int) -> int:
    """Сколько рулеток юзер закрутил сам (автолох не в счёт)."""
    total = await session.scalar(
        select(func.count())
        .select_from(LoserRoll)
        .where(LoserRoll.rolled_by == user_id, LoserRoll.source != "auto")
    )
    return int(total or 0)


async def count_chukhan(session: AsyncSession, user_id: int) -> int:
    """Сколько раз юзер был чуханом недели (только доставленные недели)."""
    total = await session.scalar(
        select(func.count())
        .select_from(WeeklyChukhan)
        .where(WeeklyChukhan.user_id == user_id, WeeklyChukhan.posted_at.is_not(None))
    )
    return int(total or 0)


async def count_polls(session: AsyncSession, user_id: int) -> int:
    total = await session.scalar(
        select(func.count()).select_from(Poll).where(Poll.created_by == user_id)
    )
    return int(total or 0)


async def count_nominations(session: AsyncSession, user_id: int) -> int:
    """Номинации игр. `added_by_tg_id` — TG-id, поэтому сверяем через users."""
    total = await session.scalar(
        select(func.count())
        .select_from(GameNomination)
        .join(User, User.telegram_id == GameNomination.added_by_tg_id)
        .where(User.id == user_id)
    )
    return int(total or 0)


# ==========================================================================
# Трекеры: события
# ==========================================================================


async def on_loser(
    session: AsyncSession,
    *,
    loser_id: int,
    roller_id: int,
    source: str,
    announce: bool = True,
) -> list[Achievement]:
    """Событие «лох выпал». Возвращает выданные ачивки.

    `source='duel'` — развлекательный прокрут (`/loser`, кнопка в мини-аппе):
    он не даёт ни опыта «лох дня», ни «С почином», но именно в нём человек сам
    крутит рулетку → идёт в счёт «Искателя истины» и может выпасть сам себе
    («Самострел»).
    """
    out: list[Achievement] = []
    if source != "duel":
        out += await _grant_counter(
            session, loser_id, SUPREME_CHUKHAN_TIER_BASE, await count_losers(session, loser_id),
            announce=announce,
        )
    if roller_id == loser_id:
        ach = await grant(session, loser_id, "self_shot", announce=announce)
        if ach:
            out.append(ach)
    else:
        out += await _grant_counter(
            session,
            roller_id,
            "truth_seeker",
            await count_started_rolls(session, roller_id),
            announce=announce,
        )
    return out


async def on_chukhan(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    return await _grant_counter(
        session, user_id, "first_worm", await count_chukhan(session, user_id),
        announce=announce,
    )


async def on_availability(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Разметка календаря: «Информатор» (месяц вперёд) и «Безработный» (4 недели)."""
    out: list[Achievement] = []

    covered = await days_covered_ahead(session, user_id)
    if covered >= INFORMANT_DAYS:
        ach = await grant(session, user_id, "informant", announce=announce)
        if ach:
            out.append(ach)

    weeks = await consecutive_availability_weeks(session, user_id)
    if weeks >= UNEMPLOYED_WEEKS:
        ach = await grant(session, user_id, "unemployed", announce=announce)
        if ach:
            out.append(ach)
    return out


async def on_poll_created(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    ach = get("vciom_agent")
    assert ach is not None and ach.threshold is not None
    return await _grant_threshold(
        session,
        user_id,
        "vciom_agent",
        await count_polls(session, user_id),
        ach.threshold,
        announce=announce,
    )


async def on_nomination(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    ach = get("nominal_nominal")
    assert ach is not None and ach.threshold is not None
    return await _grant_threshold(
        session,
        user_id,
        "nominal_nominal",
        await count_nominations(session, user_id),
        ach.threshold,
        announce=announce,
    )


async def on_game_winner(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """«Номинатор»: номинированная тобой игра выиграла (выдаётся один раз)."""
    ach = await grant(session, user_id, "nominator", announce=announce)
    return [ach] if ach else []


async def on_chukhan_reroll(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    ach = await grant(session, user_id, "rewrote_history", announce=announce)
    return [ach] if ach else []


async def on_bot_reply(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Ответ боту реплаем/упоминанием: счётчик «Укротителя паст»."""
    ach = get("worm_tamer")
    assert ach is not None and ach.threshold is not None
    count = await bump_counter(session, user_id, COUNTER_WORM_TAMER)
    return await _grant_threshold(
        session, user_id, "worm_tamer", count, ach.threshold, announce=announce
    )


async def on_meme_reactions(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Э7: пост с мемом собрал реакции → «Мемолог» + счётчик «Успешного успеха»."""
    out: list[Achievement] = []
    ach = await grant(session, user_id, "memelog", announce=announce)
    if ach:
        out.append(ach)
    succ = get("successful_success")
    assert succ is not None and succ.threshold is not None
    count = await bump_counter(session, user_id, COUNTER_SUCCESS)
    out += await _grant_threshold(
        session, user_id, "successful_success", count, succ.threshold, announce=announce
    )
    return out


async def on_dead_post(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Э7: 12 часов тишины после поста → «Forever alone» + счётчик «Опиума»."""
    out: list[Achievement] = []
    ach = await grant(session, user_id, "forever_alone", announce=announce)
    if ach:
        out.append(ach)
    opium = get("opium_for_nobody")
    assert opium is not None and opium.threshold is not None
    count = await bump_counter(session, user_id, COUNTER_OPIUM)
    out += await _grant_threshold(
        session, user_id, "opium_for_nobody", count, opium.threshold, announce=announce
    )
    return out


async def on_donation_sent(
    session: AsyncSession,
    donor_id: int,
    *,
    recipients_this_year: int,
    live_participants: int,
    announce: bool = True,
) -> list[Achievement]:
    """Э11: «Кэшбэк» (первый донат) и «Дон Корлеоне» (одарил всех живых за год)."""
    out: list[Achievement] = []
    ach = await grant(session, donor_id, "cashback", announce=announce)
    if ach:
        out.append(ach)
    if live_participants > 0 and recipients_this_year >= live_participants:
        ach = await grant(session, donor_id, "don_corleone", announce=announce)
        if ach:
            out.append(ach)
    return out


async def _claim_week_marker(
    session: AsyncSession, user_id: int, key: str
) -> bool:
    """Занять маркер идемпотентности недельного звания. False — уже занят.

    `xp_grants` — та же таблица, что хранит окна начисления XP: её назначение
    ровно «маркеры идемпотентности». Повторный прогон job'а за ту же неделю
    не должен ни второй раз поднимать счётчик, ни выдавать тир.
    """
    existing = await session.get(XpGrant, (user_id, key))
    if existing is not None:
        return False
    session.add(XpGrant(user_id=user_id, idem_key=key))
    await session.flush()
    return True


async def on_week_activity(
    session: AsyncSession,
    *,
    most_active_id: int | None,
    least_active_id: int | None,
    week_key: str | None = None,
    announce: bool = True,
) -> list[Achievement]:
    """Э6: итог недели по `chat_activity_daily` → «Рупор поколения» / «Read only».

    `None` означает «неделя без активности» — ачивку не выдаём никому.
    `week_key` (например `2026-W39`) делает вызов идемпотентным: повтор за ту же
    неделю не поднимает счётчик звания. Без него (отладка/тесты) идемпотентности
    нет — считаем каждый вызов новым итогом.
    """
    out: list[Achievement] = []
    if most_active_id is not None:
        claimed = True
        if week_key is not None:
            claimed = await _claim_week_marker(
                session, most_active_id, f"week_best:{week_key}"
            )
        if claimed:
            count = await bump_counter(session, most_active_id, COUNTER_MOUTHPIECE)
            out += await _grant_counter(
                session, most_active_id, "generation_mouthpiece", count, announce=announce
            )
    if least_active_id is not None:
        claimed = True
        if week_key is not None:
            claimed = await _claim_week_marker(
                session, least_active_id, f"week_worst:{week_key}"
            )
        if claimed:
            count = await bump_counter(session, least_active_id, COUNTER_READ_ONLY)
            out += await _grant_counter(
                session, least_active_id, "read_only", count, announce=announce
            )
    return out


async def week_activity_counts(
    session: AsyncSession, start: date, end: date
) -> dict[int, int]:
    """Сообщения по юзерам за окно `[start, end]` (включительно) — один SELECT.

    Источник — durable `chat_activity_daily` (наполняется в `awards.message`).
    Складываем сообщения по дням недели, а не берём `chat_messages`: та таблица
    чистится через 7 дней и не видит медиа/стикеры.
    """
    rows = (
        await session.execute(
            select(ChatActivityDaily.user_id, func.sum(ChatActivityDaily.messages))
            .where(ChatActivityDaily.day >= start, ChatActivityDaily.day <= end)
            .group_by(ChatActivityDaily.user_id)
        )
    ).all()
    return {int(uid): int(total or 0) for uid, total in rows}


# ==========================================================================
# Трекеры-помощники (чистые + агрегаты)
# ==========================================================================


def covered_days(
    ranges: list[tuple[datetime, datetime, bool]], start: date, days: int
) -> int:
    """Сколько дней из окна `[start, start+days)` покрыто диапазонами.

    Чистая функция (тестируется без БД). Считаем по календарным дням в UTC:
    многодневный диапазон закрывает все дни, которые пересекает.
    """
    hit: set[date] = set()
    window_end = start + timedelta(days=days)
    for starts_at, ends_at, _all_day in ranges:
        cur = max(starts_at.astimezone(timezone.utc).date(), start)
        last = min(
            ends_at.astimezone(timezone.utc).date(), window_end - timedelta(days=1)
        )
        while cur <= last:
            hit.add(cur)
            cur += timedelta(days=1)
    return len(hit)


async def days_covered_ahead(session: AsyncSession, user_id: int) -> int:
    """«Информатор»: сколько дней из ближайших 30 разметил юзер."""
    today = datetime.now(timezone.utc).date()
    horizon = datetime.combine(today + timedelta(days=INFORMANT_DAYS), time.min,
                               tzinfo=timezone.utc)
    rows = (
        await session.execute(
            select(
                AvailabilityRange.starts_at,
                AvailabilityRange.ends_at,
                AvailabilityRange.all_day,
            ).where(
                AvailabilityRange.user_id == user_id,
                AvailabilityRange.status == STATUS_FREE,
                AvailabilityRange.ends_at >= datetime.combine(today, time.min, tzinfo=timezone.utc),
                AvailabilityRange.starts_at < horizon,
            )
        )
    ).all()
    return covered_days([(s, e, a) for s, e, a in rows], today, INFORMANT_DAYS)


async def consecutive_availability_weeks(session: AsyncSession, user_id: int) -> int:
    """«Безработный»: сколько недель ПОДРЯД (с текущей назад) юзер размечал календарь.

    Источник — маркеры `xp_grants` (`availability:<ISO-нед>`, пишет `awards.py`):
    они уже точно отражают «была хотя бы одна свободная дата на этой неделе».
    """
    rows = await session.scalars(
        select(XpGrant.idem_key).where(
            XpGrant.user_id == user_id,
            XpGrant.idem_key.like("availability:%"),
        )
    )
    keys = {k.split(":", 1)[1] for k in rows.all()}
    now = datetime.now(timezone.utc)
    streak = 0
    cursor = now
    while True:
        iso = cursor.isocalendar()
        if f"{iso.year}-W{iso.week:02d}" not in keys:
            break
        streak += 1
        cursor = cursor - timedelta(weeks=1)
        if streak > 520:  # предохранитель от бесконечного цикла
            break
    return streak


def pick_week_extremes(counts: dict[int, int]) -> tuple[int | None, int | None]:
    """Кто самый активный и самый НЕактивный за неделю.

    Чистая функция. `None` — если данных нет или «победитель» набрал 0 сообщений
    (нельзя выдать «Read only» тому, кто просто не заходил, если заходили не все).
    При равенстве берём меньший user_id — детерминизм вместо случайности.
    """
    if not counts:
        return None, None
    alive = {uid: n for uid, n in counts.items() if n > 0}
    if len(alive) < 2:
        return (None, None)
    most = max(sorted(alive), key=lambda uid: (alive[uid], -uid))
    least = min(sorted(alive), key=lambda uid: (alive[uid], uid))
    return most, least
