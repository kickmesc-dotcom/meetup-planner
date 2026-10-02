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
    GameVoiceSubmission,
    GameVoiceTask,
    LoserRoll,
    MusicGameRound,
    MusicTrack,
    Poll,
    User,
    UserAchievement,
    WeeklyChukhan,
    XpGrant,
)
from app.services.game import xp
from app.services.game.achievements_catalog import (
    CATALOG,
    COMPLETIONIST_CODE,
    SUPREME_CHUKHAN_CODE,
    SUPREME_CHUKHAN_TIER,
    SUPREME_CHUKHAN_TIER_BASE,
    Achievement,
    base_achievements,
    get,
    tiers_reached,
)
from app.services.game.config import ACHIEVEMENTS_ERA_START, EV_ACHIEVEMENT

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
# Э16: серия угадываний в мьюзик-гейме. Текущая серия сбрасывается неверной
# догадкой, рекорд — нет: ачивка «На слуху» смотрится по рекорду. Счётчик
# верных догадок совпадает с кодом ачивки (как у «Укротителя паст»).
COUNTER_MUSIC_GUESS = "music_guess"
COUNTER_MUSIC_STREAK = "music_streak_best"
COUNTER_MUSIC_STREAK_CURRENT = "music_streak_current"
# Э11: задоначенный опыт. «Кэшбэк» — база «впервые», а юбилеи ×10/×20/… —
# отдельные ачивки (правило «впервые ≠ юбилей»), поэтому ведём накопитель.
COUNTER_DONATIONS = "donations_sent"
# Э18: «Опиум для никого» — честная СЕРИЯ постов подряд без реакции. Текущая
# рвётся живым постом, рекорд — нет (по нему и выдаются тиры ×3/×10/…).
COUNTER_OPIUM_BEST = "opium_streak_best"
# Э18: червь-господин и кара. Оба — накопители («впервые» + юбилеи).
COUNTER_WORM_LORD = "worm_lord"
COUNTER_PUNISH = "punisher"

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


@dataclass(frozen=True)
class AchievementStat:
    """Насколько редка ачивка: сколько участников её имеют (для сводки в профиле).

    Задание: «вместо обладателей ачивок — крохотная сводка, сколько % участников
    имеют такую». Поэтому отдаём не список имён, а процент от всех участников.
    """

    code: str
    holders: int
    total: int

    @property
    def percent(self) -> int:
        """Округлённый процент (0 — если участников нет)."""
        if self.total <= 0:
            return 0
        return round(self.holders * 100 / self.total)


async def rarity_stats(session: AsyncSession) -> list[AchievementStat]:
    """Сколько участников имеют каждую (базовую) ачивку — два SELECT, без N+1.

    Тир-коды объединяем с базовым: «С почином ×10» — это та же ачивка «С почином»
    в сводке редкости, иначе она бы считалась дважды и разнесла строки. Знаменатель
    — число зарегистрированных участников.
    """
    total = int(await session.scalar(select(func.count()).select_from(User)) or 0)
    rows = (
        await session.execute(
            select(UserAchievement.code, func.count(func.distinct(UserAchievement.user_id)))
            .group_by(UserAchievement.code)
        )
    ).all()
    holders: dict[str, int] = {}
    for code, count in rows:
        base = code.split(":", 1)[0]
        # Если тир появился у человека, у которого нет базовой записи (старые
        # данные/ручная выдача), считаем его по максимуму, а не складываем.
        holders[base] = max(holders.get(base, 0), int(count))
    return [
        AchievementStat(code=ach.code, holders=holders.get(ach.code, 0), total=total)
        for ach in base_achievements()
    ]


async def is_supreme_chukhan(session: AsyncSession, user_id: int) -> bool:
    """Носитель спец-ранга «Верховный чухан» (Э3.4: приоритетнее ранга за уровень)."""
    return await has(session, user_id, SUPREME_CHUKHAN_CODE)


async def is_completionist(session: AsyncSession, user_id: int) -> bool:
    """Собрал 100% ачивок → особый титул «Идеальный червь» (Э18)."""
    return await has(session, user_id, COMPLETIONIST_CODE)


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
        # Э14/Э15/Э16: голосовые, предложка и мьюзик-гейм.
        "voice_debut": await count_voice_submissions(session, user_id),
        "voice_winner": await count_voice_wins(session, user_id),
        "music_dj": await count_music_published(session, user_id),
        "music_spotlight": await count_music_spotlights(session, user_id),
        COUNTER_MUSIC_GUESS: await get_counter(
            session, user_id, COUNTER_MUSIC_GUESS
        ),
        "music_streak": await get_counter(session, user_id, COUNTER_MUSIC_STREAK),
        "cashback": await get_counter(session, user_id, COUNTER_DONATIONS),
        # «Опиум» показывает РЕКОРД серии постов подряд без реакции.
        "opium_for_nobody": await get_counter(session, user_id, COUNTER_OPIUM_BEST),
        "worm_lord": await get_counter(session, user_id, COUNTER_WORM_LORD),
        "punisher": await get_counter(session, user_id, COUNTER_PUNISH),
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


async def reconcile_completionist(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> bool:
    """True, если у игрока собраны ВСЕ ачивки каталога (кроме самого капстоуна).

    Выдаёт «Идеального червя», если ещё не выдан. Зовётся на поверхностях, где
    коллекция и так загружается (профиль мини-аппа, лист /ach), а не на каждой
    выдаче: так нет лишнего SELECT на каждый грант, а капстоун появляется, как
    только игрок открывает свой профиль. Сам капстоун в требуемый набор НЕ
    входит (иначе недостижим по определению).
    """
    if await has(session, user_id, COMPLETIONIST_CODE):
        return True
    collected = await collected_codes(session, user_id)
    required = set(CATALOG) - {COMPLETIONIST_CODE}
    if not required.issubset(collected):
        return False
    await grant(session, user_id, COMPLETIONIST_CODE, announce=announce)
    return True


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
    # Э19: режим публикации ачивок.
    #   instant — всегда сразу (как было);
    #   pool    — всегда в буфер, выплеснется расписанием;
    #   hybrid  — днём в живые часы и в рамках бюджета дня — сразу, а ночью /
    #             в разгар флуда / после исчерпания бюджета — в буфер, и уже
    #             утренняя сводка (`run_achievements_digest_job`) его выплеснет.
    from app.services.admin_config import get_achievements_post_mode
    from app.services.game import activity, journal

    mode = await get_achievements_post_mode(session)
    queue = mode == "pool"
    if mode == "hybrid":
        try:
            window = await activity.check_window(
                session, now=datetime.now(timezone.utc)
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("game.achievement_window_failed", error=str(exc))
            # Не смогли проверить окно — безопаснее собрать, чем разбудить чат.
            window = activity.BUSY
        queue = window != activity.OK
    if queue:
        lines = [f"{ach.icon} «{ach.title}» (+{ach.points} XP)" for ach in achs]
        return await journal.queue_achievements(
            session, user_id=user_id, lines=lines, chat_id=chat_id
        )

    text = build_announcement(name, achs)
    bot = _get_bot()
    try:
        url = await achievements_url(bot)
        markup = await _link_markup(url)
        if bot is None:
            return False
        # Э13: анонс идёт через журнал — при включённом режиме сводки он не
        # улетает в чат сразу, а ждёт ближайшего окна (см. `journal.announce`).
        sent = await journal.announce(
            session,
            kind=journal.KIND_ACHIEVEMENT,
            subject_user_id=user_id,
            text=text,
            reply_markup=markup,
        )
        if sent:
            log.info(
                "game.achievement_announced",
                user_id=user_id,
                codes=[a.code for a in achs],
            )
        return sent
    except Exception as exc:  # noqa: BLE001
        log.warning("game.achievement_announce_failed", error=str(exc))
        return False


# ==========================================================================
# Трекеры: счётчики по существующим таблицам
# ==========================================================================

_OFFICIAL_SOURCE = LoserRoll.source != "duel"

# Эра геймификации: записи ДО неё были «просто жизнью чата», а не игрой, поэтому
# в счётчиках ачивок они не участвуют (задание: отсчёт с чистого листа, но
# старые топы и опыт не обнуляем). Дату можно менять в `config.py`.
_ERA = ACHIEVEMENTS_ERA_START


async def count_losers(session: AsyncSession, user_id: int) -> int:
    """Сколько раз юзер был «лохом дня» С НАЧАЛА геймификации. Дубли
    (`source='duel'`) не считаем: это развлекательный прокрут, он не идёт даже в
    `loser_stats`."""
    total = await session.scalar(
        select(func.count())
        .select_from(LoserRoll)
        .where(
            LoserRoll.loser_user_id == user_id,
            _OFFICIAL_SOURCE,
            LoserRoll.rolled_at >= _ERA,
        )
    )
    return int(total or 0)


async def count_started_rolls(session: AsyncSession, user_id: int) -> int:
    """Сколько рулеток юзер закрутил сам (автолох не в счёт), с начала игры."""
    total = await session.scalar(
        select(func.count())
        .select_from(LoserRoll)
        .where(
            LoserRoll.rolled_by == user_id,
            LoserRoll.source != "auto",
            LoserRoll.rolled_at >= _ERA,
        )
    )
    return int(total or 0)


async def count_chukhan(session: AsyncSession, user_id: int) -> int:
    """Сколько раз юзер был чуханом недели (только доставленные недели, с начала игры)."""
    total = await session.scalar(
        select(func.count())
        .select_from(WeeklyChukhan)
        .where(
            WeeklyChukhan.user_id == user_id,
            WeeklyChukhan.posted_at.is_not(None),
            WeeklyChukhan.week_start >= _ERA,
        )
    )
    return int(total or 0)


async def count_polls(session: AsyncSession, user_id: int) -> int:
    """Опросы юзера с начала игры (у `polls` есть `created_at` с `now()`)."""
    total = await session.scalar(
        select(func.count())
        .select_from(Poll)
        .where(Poll.created_by == user_id, Poll.created_at >= _ERA)
    )
    return int(total or 0)


async def count_nominations(session: AsyncSession, user_id: int) -> int:
    """Номинации игр с начала игры. `added_by_tg_id` — TG-id, сверяем через users."""
    total = await session.scalar(
        select(func.count())
        .select_from(GameNomination)
        .join(User, User.telegram_id == GameNomination.added_by_tg_id)
        .where(User.id == user_id, GameNomination.added_at >= _ERA)
    )
    return int(total or 0)


async def count_voice_submissions(session: AsyncSession, user_id: int) -> int:
    """Э14: сколько голосовых вариантов юзер сдал с начала игры."""
    total = await session.scalar(
        select(func.count())
        .select_from(GameVoiceSubmission)
        .where(
            GameVoiceSubmission.user_id == user_id,
            GameVoiceSubmission.submitted_at >= _ERA,
        )
    )
    return int(total or 0)


async def count_voice_wins(session: AsyncSession, user_id: int) -> int:
    """Э14: сколько голосований за лучший вариант юзер выиграл с начала игры."""
    total = await session.scalar(
        select(func.count())
        .select_from(GameVoiceTask)
        .where(
            GameVoiceTask.winner_user_id == user_id,
            GameVoiceTask.created_at >= _ERA,
        )
    )
    return int(total or 0)


async def count_music_published(session: AsyncSession, user_id: int) -> int:
    """Э15: сколько треков юзера ушло в выпущенные подборки с начала игры."""
    total = await session.scalar(
        select(func.count())
        .select_from(MusicTrack)
        .where(
            MusicTrack.user_id == user_id,
            MusicTrack.status == "published",
            MusicTrack.added_at >= _ERA,
        )
    )
    return int(total or 0)


async def count_music_spotlights(session: AsyncSession, user_id: int) -> int:
    """Э16: сколько раз трек юзера выпал в мьюзик-гейме с начала игры."""
    total = await session.scalar(
        select(func.count())
        .select_from(MusicGameRound)
        .where(
            MusicGameRound.correct_user_id == user_id,
            MusicGameRound.created_at >= _ERA,
        )
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
    """Создал опрос → «Агент ВЦИОМ-а» (первый) и его юбилеи (×3, ×10, …)."""
    return await _grant_counter(
        session,
        user_id,
        "vciom_agent",
        await count_polls(session, user_id),
        announce=announce,
    )


async def on_nomination(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Номинировал игру → «Номинальный номинал» (первый) и юбилеи (×3, ×10, …)."""
    return await _grant_counter(
        session,
        user_id,
        "nominal_nominal",
        await count_nominations(session, user_id),
        announce=announce,
    )


async def _set_counter(
    session: AsyncSession, user_id: int, code: str, value: int
) -> None:
    """Присвоить счётчику точное значение (для серий: сброс/рекорд)."""
    row = await session.get(AchievementCounter, (user_id, code))
    if row is None:
        session.add(AchievementCounter(user_id=user_id, code=code, count=value))
    else:
        row.count = value
    await session.flush()


async def on_voice_submitted(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Э14: сдал голосовой вариант → «Голос из народа» и его юбилеи."""
    return await _grant_counter(
        session,
        user_id,
        "voice_debut",
        await count_voice_submissions(session, user_id),
        announce=announce,
    )


async def on_voice_winner(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Э14: вариант победил в голосовании → «Лучший голос» и его юбилеи."""
    return await _grant_counter(
        session,
        user_id,
        "voice_winner",
        await count_voice_wins(session, user_id),
        announce=announce,
    )


async def on_music_published(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Э15: трек ушёл в подборку → «Диджей недели» и его юбилеи."""
    return await _grant_counter(
        session,
        user_id,
        "music_dj",
        await count_music_published(session, user_id),
        announce=announce,
    )


async def on_music_spotlight(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Э16: трек автора выпал в мьюзик-гейме → «На виду»."""
    return await _grant_counter(
        session,
        user_id,
        "music_spotlight",
        await count_music_spotlights(session, user_id),
        announce=announce,
    )


async def on_music_guess(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Э16: верная догадка → «Меломан» + рост серии («На слуху»).

    Серия живёт в счётчиках, а не в таблице раундов: неверные догадки нигде не
    хранятся, поэтому «сколько подряд» из данных не вывести. Своя пара
    счётчиков (текущая серия + рекорд) закрывает это точно.
    """
    count = await bump_counter(session, user_id, COUNTER_MUSIC_GUESS)
    out = await _grant_counter(
        session, user_id, "music_guess", count, announce=announce
    )

    current = await get_counter(session, user_id, COUNTER_MUSIC_STREAK_CURRENT) + 1
    await _set_counter(session, user_id, COUNTER_MUSIC_STREAK_CURRENT, current)
    best = await get_counter(session, user_id, COUNTER_MUSIC_STREAK)
    if current > best:
        await _set_counter(session, user_id, COUNTER_MUSIC_STREAK, current)
        best = current

    ach = get("music_streak")
    if ach is not None and ach.threshold is not None:
        out += await _grant_threshold(
            session,
            user_id,
            "music_streak",
            best,
            ach.threshold,
            announce=announce,
        )
    await session.commit()
    return out


async def on_music_miss(session: AsyncSession, user_id: int) -> None:
    """Э16: неверная догадка обнуляет ТЕКУЩУЮ серию (рекорд не трогаем)."""
    if await get_counter(session, user_id, COUNTER_MUSIC_STREAK_CURRENT) != 0:
        await _set_counter(session, user_id, COUNTER_MUSIC_STREAK_CURRENT, 0)
        await session.commit()


async def on_music_round_closed(
    session: AsyncSession, *, guessed_ids: set[int], poll_arrived: bool
) -> int:
    """Пропуск раунда рвёт серию угадываний (рекорд не трогаем). Э18.

    Сбрасываем текущую серию у всех, кто в этом раунде НЕ угадал: если просто не
    участвовать, серию больше не сохранить. Если опрос не долетел (stale-раунд,
    сбой доставки) — не трогаем: это не вина игрока.
    """
    if not poll_arrived:
        return 0
    rows = await session.scalars(
        select(AchievementCounter).where(
            AchievementCounter.code == COUNTER_MUSIC_STREAK_CURRENT,
            AchievementCounter.count > 0,
        )
    )
    reset = 0
    for row in rows.all():
        if int(row.user_id) in guessed_ids:
            continue
        row.count = 0
        reset += 1
    if reset:
        await session.flush()
    return reset


async def on_worm_lord(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Э18: стал червём-господином (повелителем бота) → «Червь-господин» + юбилеи."""
    count = await bump_counter(session, user_id, COUNTER_WORM_LORD)
    return await _grant_counter(
        session, user_id, "worm_lord", count, announce=announce
    )


async def on_punish(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Э18: применил /punish (червь-господин натравил бота) → «Каратель» + юбилеи."""
    count = await bump_counter(session, user_id, COUNTER_PUNISH)
    return await _grant_counter(
        session, user_id, "punisher", count, announce=announce
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
    """Ответ боту реплаем/упоминанием: «Укротитель паст» (первый) и юбилеи."""
    count = await bump_counter(session, user_id, COUNTER_WORM_TAMER)
    return await _grant_counter(
        session, user_id, "worm_tamer", count, announce=announce
    )


async def on_meme_all_reacted(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Э7: на мем отреагировали ВСЕ живые участники → «Мемолог».

    Отдельно от счётчика «Успешного успеха»: «все отреагировали» и «пост собрал
    хоть одну реакцию» — разные события, и первое не должно выпадать каждому,
    кому просто ответили смайликом.
    """
    ach = await grant(session, user_id, "memelog", announce=announce)
    return [ach] if ach else []


async def on_meme_reactions(
    session: AsyncSession, user_id: int, *, announce: bool = True
) -> list[Achievement]:
    """Э7: пост закрылся С реакциями → «Успешный успех» + ОБРЫВ серии «Опиума».

    Живой пост — это и есть «не подряд»: текущая серия постов в пустоту рвётся
    (рекорд не трогаем — по нему выдаются тиры).
    """
    count = await bump_counter(session, user_id, COUNTER_SUCCESS)
    out = await _grant_counter(
        session, user_id, "successful_success", count, announce=announce
    )
    if await get_counter(session, user_id, COUNTER_OPIUM) != 0:
        await _set_counter(session, user_id, COUNTER_OPIUM, 0)
    return out


async def on_dead_post(
    session: AsyncSession,
    user_id: int,
    *,
    silent_chat: bool = True,
    announce: bool = True,
) -> list[Achievement]:
    """Э7: 12 часов без откликов на пост.

    - счётчик «Опиума» растёт всегда: это и есть «пост, на который не
      отреагировали 12 часов»;
    - «Forever alone» — только если в чате вообще молчали (`silent_chat`):
      мем, проигнорированный посреди живого флуда, — не «forever alone».
    """
    out: list[Achievement] = []
    if silent_chat:
        ach = await grant(session, user_id, "forever_alone", announce=announce)
        if ach:
            out.append(ach)
    current = await bump_counter(session, user_id, COUNTER_OPIUM)
    best = await get_counter(session, user_id, COUNTER_OPIUM_BEST)
    if current > best:
        await _set_counter(session, user_id, COUNTER_OPIUM_BEST, current)
        best = current
    out += await _grant_counter(
        session, user_id, "opium_for_nobody", best, announce=announce
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
    """Э11: «Кэшбэк» (первый донат + юбилеи) и «Дон Корлеоне» (одарил всех живых).

    «Кэшбэк» — накопитель: база берётся за ПЕРВЫЙ донат, а ×10/×20/… — отдельные
    ачивки за юбилеи (одно жёсткое правило проекта «впервые ≠ юбилей»).
    """
    out: list[Achievement] = []
    count = await bump_counter(session, donor_id, COUNTER_DONATIONS)
    out += await _grant_counter(session, donor_id, "cashback", count, announce=announce)
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
    # Через `xp.grant_exists`, а не `session.get(XpGrant, (user_id, key))`: у
    # `XpGrant` суррогатный PK `id`, и `get` по паре падает на сборке PK —
    # ошибка уходила бы в `awards._guarded`, который делает rollback и экспайрит
    # объекты вызывающего (отсюда 500 при сохранении календаря).
    existing = await xp.grant_exists(session, user_id, key)
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
