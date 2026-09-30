"""GHG10 Э14: голосовые задания — постановка, приём, сводка и опрос.

Механика одной строкой: бот ставит творческую задачу («запиши голосовуху, как
крякает утка»), окно сбора идёт несколько часов, ответы принимаются голосовыми —
реплаем на сообщение-задание или боту в личку; по истечении окна бот вывешивает
сводку с ПОДКРЕПЛЕНИЕМ (пересылает сами голосовые с подписью, кто это прислал),
а если включён опрос — добавляет голосование «чей вариант лучше» с бонусом
победителю.

Три предохранителя (задание пишет в чат само, без запроса):

* **Не ночью.** Постановка только в дневном окне по локальному времени чата
  (`VOICE_DAY_START_HOUR`..`VOICE_DAY_END_HOUR`) — «активностей в два часа ночи»
  не бывает.
* **Раз в пару дней.** `game.voice.min_gap_hours` (дефолт 48) между заданиями.
* **Без повторов.** Задание уходит в кулдаун (`cooldown_days`), а не сыплется
  одним и тем же подряд.

Файлы НЕ храним: только `file_id` (хост слабый). На участника — одна сдача на
задание (уникальность в БД), поэтому опыт не начислить дважды.

Тот же принцип, что у остальных игровых модулей: чистая логика (окно, выбор
задания, тексты) — отдельно и тестируется без БД/сети; I/O — тонким слоем.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import GameVoiceSubmission, GameVoiceTask, User
from app.services.admin_config import (
    get_game_voice_enabled,
    get_game_voice_min_gap_hours,
    get_game_voice_poll_enabled,
)
from app.services.game import awards, journal
from app.services.game.config import (
    VOICE_DAY_END_HOUR,
    VOICE_DAY_START_HOUR,
    VOICE_POLL_MAX_OPTIONS,
    VOICE_POLL_MIN_OPTIONS,
    VOICE_POLL_MINUTES,
    VOICE_POLL_REWARD,
    VOICE_TZ_OFFSET_HOURS,
)
from app.services.game.voice_catalog import TASKS, TASKS_BY_CODE, VoiceTask

log = structlog.get_logger()

# Статусы сдачи — по ним хендлер решает, что ответить в чат/личку.
OK = "ok"
NO_TASK = "no_task"
CLOSED = "closed"
UNKNOWN_USER = "unknown_user"
ALREADY = "already"


# --------------------------------------------------------------------------
# Чистая часть: время, выбор задания, тексты
# --------------------------------------------------------------------------


def local_hour(now: datetime) -> int:
    """Час в ЛОКАЛЬНОМ времени чата (UTC + смещение). Чистая функция."""
    return (now.astimezone(timezone.utc).hour + VOICE_TZ_OFFSET_HOURS) % 24


def is_daytime(now: datetime) -> bool:
    """Можно ли вообще ставить задание в этот час. Чистая функция.

    Верхняя граница исключающая: в 20:00 новое задание уже не ставим, чтобы окно
    сбора не растянулось на ночь.
    """
    return VOICE_DAY_START_HOUR <= local_hour(now) < VOICE_DAY_END_HOUR


def pick_task(*, used_codes: set[str], rng: random.Random) -> VoiceTask | None:
    """Задание вне кулдауна. Чистая функция (тесты). `None` — все на кулдауне."""
    free = [t for t in TASKS if t.code not in used_codes]
    if not free:
        return None
    return rng.choice(free)


def build_task_text(
    task: VoiceTask, *, expires_at: datetime, bot_username: str | None
) -> str:
    """Текст задания в чат. Чистая функция.

    Все числа (окно, награда, время) подставляются здесь, чтобы текст в БД и в
    чате не разъезжались.
    """
    local_until = (expires_at.astimezone(timezone.utc) + timedelta(hours=VOICE_TZ_OFFSET_HOURS))
    hours = max(1, round(task.window_minutes / 60))
    dm = f"боту в личку @{bot_username}" if bot_username else "боту в личку"
    return (
        f"{task.text}\n\n"
        f"🎙 Отвечай <b>голосовым</b>: реплаем на это сообщение или {dm}.\n"
        f"⏳ Приём около {hours} ч (до {local_until.strftime('%H:%M')}). "
        f"Награда: <b>+{task.reward} XP</b> за вариант."
    )


def summary_header(*, title: str, count: int) -> str:
    """Заголовок сводки. Чистая функция."""
    if count <= 0:
        return f"🎙 Задание «{title}» закрыто: <b>никто не прислал</b>. В следующий раз смелее."
    return f"🎙 Задание «{title}» закрыто. Прислали <b>{count}</b> вариант(ов):"


def variant_caption(*, index: int, name: str) -> str:
    """Подпись под пересланным голосовым. Чистая функция."""
    return f"№{index} — <b>{name}</b>"


def poll_question() -> str:
    return "🎙 Чей вариант лучше?"


# --------------------------------------------------------------------------
# Бот и username
# --------------------------------------------------------------------------


def _username(bot) -> str | None:  # noqa: ANN001
    """Username бота для подсказки «напиши в личку». None — если не добыли.

    Берём из кэша `bot._me` (как `achievements.achievements_url`): не ходим в сеть
    ради подсказки. Если username не добыли — текст скажет просто «в личку».
    """
    if bot is None:
        return None
    try:
        me = getattr(bot, "_me", None)
        if me is None:
            maybe = getattr(bot, "me", None)
            if hasattr(maybe, "username"):
                me = maybe
        return getattr(me, "username", None) or None
    except Exception:  # noqa: BLE001
        return None


async def _user_names(session: AsyncSession, ids: list[int]) -> dict[int, str]:
    """user_id → display_name одним SELECT (без N+1)."""
    if not ids:
        return {}
    rows = await session.execute(
        select(User.id, User.display_name).where(User.id.in_(ids))
    )
    return {int(uid): name for uid, name in rows.all()}


# --------------------------------------------------------------------------
# Открытие задания
# --------------------------------------------------------------------------


async def _used_codes(session: AsyncSession, *, now: datetime) -> set[str]:
    """Коды заданий, которые сейчас на кулдауне."""
    used: set[str] = set()
    for task in TASKS:
        since = now - timedelta(days=task.cooldown_days)
        recent = await session.scalar(
            select(func.count())
            .select_from(GameVoiceTask)
            .where(GameVoiceTask.code == task.code, GameVoiceTask.created_at >= since)
        )
        if recent:
            used.add(task.code)
    return used


async def _has_open_task(session: AsyncSession, *, now: datetime) -> bool:
    found = await session.scalar(
        select(GameVoiceTask.id)
        .where(GameVoiceTask.closed_at.is_(None), GameVoiceTask.expires_at > now)
        .limit(1)
    )
    return found is not None


async def open_task(
    session: AsyncSession,
    bot,
    *,
    now: datetime,
    rng: random.Random,
) -> GameVoiceTask | None:
    """Поставить новое задание. None — не получилось (нет чата/все на кулдауне/TG)."""
    settings = get_settings()
    chat_id = settings.group_chat_id
    if not chat_id:
        return None
    task = pick_task(used_codes=await _used_codes(session, now=now), rng=rng)
    if task is None:
        return None
    expires_at = now + timedelta(minutes=task.window_minutes)
    text = build_task_text(task, expires_at=expires_at, bot_username=_username(bot))
    if bot is None:
        return None
    try:
        # ⚠️ Отправляем ДО записи в БД (как `games_poll`): если TG не принял,
        # «висящего» задания без сообщения в чате не остаётся.
        message = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        log.warning("game.voice_send_failed", code=task.code, error=str(exc))
        return None
    row = GameVoiceTask(
        chat_id=chat_id,
        code=task.code,
        text=text,
        reward=task.reward,
        tg_message_id=message.message_id,
        expires_at=expires_at,
        poll_enabled=await get_game_voice_poll_enabled(session),
    )
    session.add(row)
    await session.commit()
    log.info("game.voice_opened", code=task.code, task_id=row.id)
    return row


# --------------------------------------------------------------------------
# Сводка и опрос
# --------------------------------------------------------------------------


async def _submissions(
    session: AsyncSession, task_id: int
) -> list[GameVoiceSubmission]:
    rows = await session.scalars(
        select(GameVoiceSubmission)
        .where(GameVoiceSubmission.task_id == task_id)
        .order_by(GameVoiceSubmission.submitted_at.asc(), GameVoiceSubmission.id.asc())
    )
    return list(rows)


async def finalize_task(
    session: AsyncSession, bot, task: GameVoiceTask, *, now: datetime
) -> bool:
    """Закрыть задание: сводка с пересылкой вариантов (+ опрос). True — закрыли.

    Идемпотентно: повторный вызов на уже закрытом задании ничего не делает.
    """
    if task.closed_at is not None:
        return False
    subs = await _submissions(session, task.id)
    names = await _user_names(session, [s.user_id for s in subs])
    catalog_task = TASKS_BY_CODE.get(task.code)
    title = catalog_task.title if catalog_task else task.code

    if bot is not None:
        try:
            await bot.send_message(
                chat_id=task.chat_id,
                text=summary_header(title=title, count=len(subs)),
                parse_mode="HTML",
            )
            # «Подкрепление»: сами голосовые с подписью, кто прислал.
            for idx, sub in enumerate(subs, start=1):
                try:
                    await bot.send_voice(
                        chat_id=task.chat_id,
                        voice=sub.file_id,
                        caption=variant_caption(
                            index=idx, name=names.get(sub.user_id, "участник")
                        ),
                        parse_mode="HTML",
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("game.voice_summary_voice_failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.warning("game.voice_summary_failed", error=str(exc))

    task.closed_at = now
    task.summary_sent_at = now
    task.outcome = "summary"

    # Опрос «чей вариант лучше» — только если включён и есть из кого выбирать.
    if (
        task.poll_enabled
        and len(subs) >= VOICE_POLL_MIN_OPTIONS
        and bot is not None
    ):
        await _create_poll(session, bot, task, subs=subs, names=names)
    await session.commit()
    log.info("game.voice_closed", task_id=task.id, submissions=len(subs))
    return True


async def _create_poll(
    session: AsyncSession,
    bot,
    task: GameVoiceTask,
    *,
    subs: list[GameVoiceSubmission],
    names: dict[int, str],
) -> None:
    """Создать Telegram-опрос по вариантам. Ошибка TG не ломает сводку."""
    capped = subs[:VOICE_POLL_MAX_OPTIONS]
    if len(capped) < VOICE_POLL_MIN_OPTIONS:
        return
    options = [names.get(s.user_id, f"Вариант {i}") for i, s in enumerate(capped, 1)]
    try:
        message = await bot.send_poll(
            chat_id=task.chat_id,
            question=poll_question(),
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
            open_period=VOICE_POLL_MINUTES * 60,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("game.voice_poll_send_failed", error=str(exc))
        return
    poll = message.poll
    if poll is None:
        return
    task.tg_poll_id = poll.id
    task.poll_user_ids = [s.user_id for s in capped]
    task.outcome = "poll"


async def finalize_expired(
    session: AsyncSession, bot, *, now: datetime
) -> int:
    """Закрыть все задания с истёкшим окном. Возвращает число закрытых."""
    rows = (
        await session.scalars(
            select(GameVoiceTask)
            .where(
                GameVoiceTask.closed_at.is_(None),
                GameVoiceTask.expires_at <= now,
            )
            .order_by(GameVoiceTask.id.asc())
        )
    ).all()
    closed = 0
    for task in rows:
        if await finalize_task(session, bot, task, now=now):
            closed += 1
    return closed


# --------------------------------------------------------------------------
# Приём сдачи
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SubmitResult:
    """Итог попытки сдать голосовое. `name` — имя сдавшего (для ответа)."""

    status: str
    task: GameVoiceTask | None = None
    name: str | None = None
    reward: int = 0

    @property
    def ok(self) -> bool:
        return self.status == OK


async def _find_task_for(
    session: AsyncSession,
    *,
    chat_id: int | None,
    reply_to_message_id: int | None,
) -> GameVoiceTask | None:
    """Задание, к которому относится голосовое.

    В группе — строго реплай на сообщение-задание (иначе бот хватал бы любое
    голосовое в чате). В личке — последнее задание (оно одно на чат).
    """
    if reply_to_message_id is not None:
        return await session.scalar(
            select(GameVoiceTask)
            .where(GameVoiceTask.tg_message_id == reply_to_message_id)
            .order_by(GameVoiceTask.id.desc())
            .limit(1)
        )
    return await session.scalar(
        select(GameVoiceTask).order_by(GameVoiceTask.id.desc()).limit(1)
    )


async def submit(
    session: AsyncSession,
    *,
    telegram_id: int,
    file_id: str,
    duration: int | None = None,
    tg_message_id: int | None = None,
    chat_id: int | None = None,
    reply_to_message_id: int | None = None,
    at: datetime | None = None,
) -> SubmitResult:
    """Принять голосовое как вариант. Никогда не бросает — статус в результате."""
    moment = at or datetime.now(timezone.utc)
    task = await _find_task_for(
        session, chat_id=chat_id, reply_to_message_id=reply_to_message_id
    )
    if task is None:
        return SubmitResult(NO_TASK)
    if task.closed_at is not None or task.expires_at <= moment:
        return SubmitResult(CLOSED, task=task)

    user_id = await session.scalar(
        select(User.id).where(User.telegram_id == telegram_id)
    )
    if user_id is None:
        return SubmitResult(UNKNOWN_USER, task=task)
    name = await session.scalar(
        select(User.display_name).where(User.id == int(user_id))
    )

    session.add(
        GameVoiceSubmission(
            task_id=task.id,
            user_id=int(user_id),
            file_id=file_id,
            tg_message_id=tg_message_id,
            duration=duration,
            submitted_at=moment,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # Гонка/повтор: одна сдача на участника — второй вариант не принимаем.
        await session.rollback()
        return SubmitResult(ALREADY, task=task, name=name)

    # Опыт — ПОСЛЕ своего commit'а (инвариант фасада `awards`).
    await awards.voice(
        session, int(user_id), points=task.reward, task_id=task.id, at=moment
    )
    await journal.announce(
        session,
        kind=journal.KIND_EVENT,
        subject_user_id=int(user_id),
        text=(
            f"🎙 <b>{name or 'Участник'}</b> сдал вариант в задании "
            f"(+{task.reward} XP)."
        ),
    )
    log.info("game.voice_submitted", task_id=task.id, user_id=int(user_id))
    return SubmitResult(OK, task=task, name=name, reward=task.reward)


# --------------------------------------------------------------------------
# Голосование «чей вариант лучше»
# --------------------------------------------------------------------------


async def find_task_by_poll(
    session: AsyncSession, tg_poll_id: str
) -> GameVoiceTask | None:
    return await session.scalar(
        select(GameVoiceTask).where(GameVoiceTask.tg_poll_id == tg_poll_id)
    )


def pick_winner_index(voter_counts: list[int]) -> int | None:
    """Индекс победителя голосования. Чистая функция.

    `None` — никто не голосовал. При равенстве берём меньший индекс (раньше
    сдал — раньше победил): детерминизм вместо случайности.
    """
    best_index: int | None = None
    best_count = 0
    for index, count in enumerate(voter_counts):
        if count > best_count:
            best_index, best_count = index, count
    return best_index


async def handle_poll_closed(
    session: AsyncSession, bot, *, poll, task: GameVoiceTask
) -> bool:
    """Обработать закрытие опроса: наградить победителя и огласить.

    `True` — победитель определён и награждён. Повторный вызов (TG умеет
    редоставлять апдейты) безопасен: `winner_user_id` выставляется один раз.
    """
    if task.winner_user_id is not None:
        return False
    options = list(poll.options or [])
    user_ids = list(task.poll_user_ids or [])
    counts = [int(opt.voter_count or 0) for opt in options]
    index = pick_winner_index(counts)
    if index is None or index >= len(user_ids):
        return False

    winner_id = int(user_ids[index])
    task.winner_user_id = winner_id
    task.outcome = "poll"
    await session.commit()

    await awards.voice_best(
        session, winner_id, points=VOICE_POLL_REWARD, task_id=task.id
    )
    name = await session.scalar(select(User.display_name).where(User.id == winner_id))
    await journal.announce(
        session,
        kind=journal.KIND_EVENT,
        subject_user_id=winner_id,
        text=(
            f"🏆 Лучший вариант в задании — у <b>{name or 'участника'}</b>: "
            f"+{VOICE_POLL_REWARD} XP."
        ),
    )
    log.info("game.voice_poll_won", task_id=task.id, user_id=winner_id)
    return True


# --------------------------------------------------------------------------
# Job планировщика
# --------------------------------------------------------------------------


async def run_voice_job(
    bot, *, now: datetime | None = None, rng: random.Random | None = None
) -> dict[str, int]:
    """Тик планировщика: закрыть просроченные и, если можно, поставить новое."""
    from app.db.base import get_sessionmaker

    moment = now or datetime.now(timezone.utc)
    dice = rng or random.Random()
    sm = get_sessionmaker()
    closed = 0
    opened = 0
    async with sm() as session:
        closed = await finalize_expired(session, bot, now=moment)
        if not await get_game_voice_enabled(session):
            return {"closed": closed, "opened": 0}
        if await _has_open_task(session, now=moment):
            return {"closed": closed, "opened": 0}

        last_at = await session.scalar(select(func.max(GameVoiceTask.created_at)))
        gap_hours = await get_game_voice_min_gap_hours(session)
        if last_at is not None:
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=timezone.utc)
            if moment - last_at < timedelta(hours=gap_hours):
                return {"closed": closed, "opened": 0}

        # Не ночью: задание ставим только в дневном окне чата.
        if not is_daytime(moment):
            return {"closed": closed, "opened": 0}

        task = await open_task(session, bot, now=moment, rng=dice)
        opened = 1 if task is not None else 0
    return {"closed": closed, "opened": opened}
