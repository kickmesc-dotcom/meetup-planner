"""Э16 (GHG8 H.8): мьюзик-гейм — «угадай, кто предложил трек».

Механика одной строкой: бот выдёргивает СЛУЧАЙНЫЙ трек из музыкальной
предложки (Э15) и запускает опрос «кто его предложил»; варианты — верный автор
плюс отвлекающие (другие, кто что-то присылал). Когда опрос закрывается, бот
оглашает автора и награждает его, а также всех, кто угадал.

Почему так, а не «победил самый популярный вариант»: правильный ответ в игре
один — это автор трека, а не тот, за кого больше голосов. Поэтому «угадал» =
выбрал опцию автора; такие голоса копятся в `correct_voter_ids` по
`poll_answer` (Telegram о закрытии опроса отдаёт только `voter_count` по опциям).

Три предохранителя (как у остальных игровых модулей):

* **Не спамить.** Авто-вызов — опция (по умолчанию выкл), максимум раз в неделю;
  пока открыт предыдущий раунд, новый не начинается.
* **Не повторяться.** Трек, выпавший в игре, больше в игру не попадает (память —
  сам факт записи раунда). Одному и тому же треку второй раз не удивляются.
* **Слабый хост.** Никаких поллингов в цикле: job тикает редко и сам решает
  «пора/не пора». `file_id`/ссылки, файлы не держим.

Чистая логика (уникальные подписи вариантов, верный индекс, тексты) — отдельно и
тестируется без БД/сети; I/O — тонким слоем.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import MusicGameRound, MusicTrack, User
from app.services.admin_config import (
    get_game_music_game_enabled,
    get_game_music_game_hour,
    get_game_music_game_weekday,
)
from app.services.game import awards, journal
from app.services.game import music as music_service
from app.services.game.config import (
    MUSIC_GAME_AUTHOR_REWARD,
    MUSIC_GAME_GUESS_REWARD,
    MUSIC_GAME_HISTORY_LIMIT,
    MUSIC_GAME_MAX_OPTIONS,
    MUSIC_GAME_MIN_OPTIONS,
    MUSIC_GAME_POLL_MINUTES,
)

log = structlog.get_logger()

# Состояние раунда.
OUTCOME_POLL = "poll"
OUTCOME_STALE = "stale"


# --------------------------------------------------------------------------
# Чистая логика
# --------------------------------------------------------------------------


def guess_question() -> str:
    return "🎵 Угадай, кто предложил этот трек:"


def round_lead_text(track: MusicTrack) -> str:
    """Подводка перед опросом. Чистая функция (тесты).

    Для ссылочного трека показываем саму ссылку; у аудио её нет — там подводка
    короткая, а сам файл уезжает отдельным сообщением (`file_id`).
    """
    title = track.title or track.performer or "без названия"
    if track.performer and track.title and track.performer not in title:
        title = f"{track.performer} — {track.title}"
    line = f"🎵 <b>{title}</b>"
    if track.kind == "link" and track.url:
        line += f"\n{track.url}"
    return (
        f"{line}\n\n"
        "Слушаем и угадываем, кто из наших это притащил. "
        "Правильный ответ — в конце голосования."
    )


def answer_text(name: str) -> str:
    return f"🎵 Правильный ответ: этот трек предложил(а) <b>{name}</b>."


def guesses_text(names: list[str], *, reward: int) -> str:
    """Итог по угадавшим. Чистая функция. Пусто — пустая строка."""
    if not names:
        return "🎵 На этот раз никто не угадал. В следующий раз повезёт."
    joined = ", ".join(names)
    return f"🏆 Угадали: {joined} — по +{reward} XP каждому."


def dedupe_labels(labels: list[str]) -> list[str]:
    """Сделать подписи вариантов различимыми. Чистая функция (тесты).

    Telegram отвергает опрос с одинаковыми вариантами, а два участника с
    одинаковым отображаемым именем — реальность. Второй «Митян» становится
    «Митян (2)» и так далее; индекс варианта при этом не меняется.
    """
    seen: dict[str, int] = {}
    out: list[str] = []
    for label in labels:
        base = label
        if base not in seen:
            seen[base] = 1
            out.append(base)
            continue
        seen[base] += 1
        candidate = f"{base} ({seen[base]})"
        while candidate in seen:
            seen[base] += 1
            candidate = f"{base} ({seen[base]})"
        seen[candidate] = 1
        out.append(candidate)
    return out


def options_for(
    author_id: int,
    proposer_ids: list[int],
    *,
    rng: random.Random,
    max_options: int = MUSIC_GAME_MAX_OPTIONS,
) -> list[int]:
    """Варианты опроса: автор + случайные отвлекающие. Чистая функция (тесты).

    Вернёт `[]`, если кандидатов меньше минимума (игра не имеет смысла). Автор
    всегда в списке; порядок перемешан, чтобы его позиция не была угадываемой.
    """
    others = [uid for uid in proposer_ids if uid != author_id]
    if len(others) + 1 < MUSIC_GAME_MIN_OPTIONS:
        return []
    decoys = others
    if len(decoys) > max_options - 1:
        decoys = rng.sample(decoys, max_options - 1)
    options = [author_id, *decoys]
    rng.shuffle(options)
    return options


def correct_index(option_user_ids: list[int], correct_user_id: int) -> int | None:
    """Индекс варианта автора в опросе. Чистая функция. `None` — автора нет."""
    try:
        return list(option_user_ids).index(correct_user_id)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Выборка треков-претендентов
# --------------------------------------------------------------------------


async def _used_track_ids(session: AsyncSession) -> list[int]:
    rows = await session.scalars(
        select(MusicGameRound.track_id).where(MusicGameRound.track_id.is_not(None))
    )
    return [int(r) for r in rows if r is not None]


async def eligible_tracks(session: AsyncSession) -> list[MusicTrack]:
    """Треки, которые в игре ещё не были (память об использованных)."""
    used = await _used_track_ids(session)
    stmt = (
        select(MusicTrack)
        .where(MusicTrack.status != music_service.STATUS_REMOVED)
        .order_by(MusicTrack.added_at.asc(), MusicTrack.id.asc())
    )
    if used:
        stmt = stmt.where(MusicTrack.id.not_in(used))
    return list(await session.scalars(stmt))


async def proposer_ids(session: AsyncSession) -> list[int]:
    """Кто вообще присылал треки — из них и берём отвлекающих. Один SELECT."""
    rows = await session.scalars(
        select(MusicTrack.user_id)
        .where(MusicTrack.status != music_service.STATUS_REMOVED)
        .distinct()
    )
    return [int(r) for r in rows if r is not None]


async def _names(session: AsyncSession, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(User.id, User.display_name).where(User.id.in_(ids))
    )
    return {int(uid): name for uid, name in rows.all()}


# --------------------------------------------------------------------------
# Открытие раунда
# --------------------------------------------------------------------------


async def open_round(
    session: AsyncSession,
    bot,
    *,
    now: datetime,
    rng: random.Random,
    scheduled_for: datetime | None = None,
) -> MusicGameRound | None:
    """Начать раунд. `None` — нет кандидатов/чата/TG не принял."""
    settings = get_settings()
    chat_id = settings.group_chat_id
    if not chat_id or bot is None:
        return None

    proposers = await proposer_ids(session)
    if len(proposers) < MUSIC_GAME_MIN_OPTIONS:
        return None
    tracks = await eligible_tracks(session)
    if not tracks:
        return None

    track = rng.choice(tracks)
    options = options_for(track.user_id, proposers, rng=rng)
    if not options:
        return None
    names = await _names(session, options)
    labels = dedupe_labels([names.get(uid, f"Участник {index + 1}") for index, uid in enumerate(options)])

    try:
        lead = await bot.send_message(
            chat_id=chat_id, text=round_lead_text(track), parse_mode="HTML"
        )
        if track.kind == "audio" and track.file_id:
            try:
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=track.file_id,
                    caption=track.title or track.performer or "",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("game.music_game_audio_failed", error=str(exc))
        poll_message = await bot.send_poll(
            chat_id=chat_id,
            question=guess_question(),
            options=labels,
            is_anonymous=False,
            allows_multiple_answers=False,
            open_period=MUSIC_GAME_POLL_MINUTES * 60,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("game.music_game_send_failed", error=str(exc))
        return None

    poll = poll_message.poll
    if poll is None:
        return None
    row = MusicGameRound(
        chat_id=chat_id,
        track_id=track.id,
        correct_user_id=track.user_id,
        tg_message_id=lead.message_id,
        tg_poll_id=poll.id,
        option_user_ids=list(options),
        correct_voter_ids=[],
        scheduled_for=scheduled_for,
    )
    session.add(row)
    await session.commit()
    log.info("game.music_game_opened", round_id=row.id, track_id=track.id)
    return row


# --------------------------------------------------------------------------
# Приём догадок и закрытие
# --------------------------------------------------------------------------


async def find_round_by_poll(
    session: AsyncSession, tg_poll_id: str
) -> MusicGameRound | None:
    return await session.scalar(
        select(MusicGameRound)
        .where(MusicGameRound.tg_poll_id == tg_poll_id)
        .order_by(MusicGameRound.id.desc())
        .limit(1)
    )


async def register_guess(
    session: AsyncSession,
    *,
    round: MusicGameRound,
    user_id: int,
    option_index: int,
) -> bool:
    """Запомнить верную догадку. `True` — впервые угадал.

    Telegram шлёт `poll_answer` и при смене голоса; если человек ушёл с верной
    опции на неверную, мы его отметку не снимаем (право на ошибку уже
    использовано) — так игра не наказывает за любопытство.
    """
    if round.closed_at is not None:
        return False
    # Э18 anti-grief: автор трека знает свой трек, поэтому его голос не считаем.
    # Иначе сабмит трека + голос за себя давали бы и `music_author`, и
    # `music_guess` (плюс серию) за одно действие — оператор: «не засчитывать
    # ответ, если его написал сам инициатор события». Тихо игнорируем: это не
    # промах, серию рвать нечем.
    if round.correct_user_id is not None and int(round.correct_user_id) == user_id:
        return False
    index = correct_index(list(round.option_user_ids or []), int(round.correct_user_id or -1))
    if index is None or index != option_index:
        # Э17: неверная догадка обнуляет ТЕКУЩУЮ серию угадываний. Но только если
        # человек ещё не угадал этот раунд: смена верного голоса на неверный —
        # это любопытство, а не промах, и серию рвать не должна.
        if user_id not in list(round.correct_voter_ids or []):
            await awards.music_miss(session, user_id)
        return False
    voters = list(round.correct_voter_ids or [])
    if user_id in voters:
        return False
    voters.append(user_id)
    # JSONB-колонку переписываем НОВЫМ списком: SQLAlchemy не увидит мутацию.
    round.correct_voter_ids = voters
    await session.commit()
    log.info("game.music_game_guess", round_id=round.id, user_id=user_id)
    return True


@dataclass(frozen=True)
class RoundResult:
    round_id: int
    author_id: int | None
    guessed_ids: list[int]


async def finalize_round(
    session: AsyncSession,
    bot,
    round: MusicGameRound,
    *,
    now: datetime,
    poll=None,  # noqa: ANN001 — aiogram Poll | None
) -> RoundResult | None:
    """Закрыть раунд: огласить автора, наградить его и угадавших.

    Идемпотентно: повторный вызов (TG умеет редоставлять апдейты, job тоже может
    догнать) на уже закрытом раунде ничего не делает.
    """
    if round.closed_at is not None:
        return None

    round.closed_at = now
    round.outcome = OUTCOME_POLL if poll is not None else OUTCOME_STALE
    await session.commit()  # фиксируем «закрыт» ДО начислений (инвариант awards)

    author_id = int(round.correct_user_id) if round.correct_user_id is not None else None
    guessed_ids = [int(uid) for uid in (round.correct_voter_ids or [])]
    # Э18 anti-grief (страховка): старые раунды могли записаться до гварда в
    # `register_guess` — автор всё равно не должен получать XP за «угадывание»
    # своего же трека и это не должно считаться промахом серии.
    if author_id is not None:
        guessed_ids = [uid for uid in guessed_ids if uid != author_id]
    # Э18: пропуск раунда рвёт серию угадываний (только при реально закрытом
    # опросе — сбой доставки игрока не наказывает).
    from app.services.game import achievements as _achievements

    await _achievements.on_music_round_closed(
        session, guessed_ids=set(guessed_ids), poll_arrived=poll is not None
    )
    names = await _names(session, [uid for uid in ([author_id] if author_id else []) + guessed_ids if uid is not None])

    if bot is not None:
        try:
            if author_id is not None:
                await bot.send_message(
                    chat_id=round.chat_id,
                    text=answer_text(names.get(author_id, "участник")),
                    parse_mode="HTML",
                )
            guessed_names = [names.get(uid, "участник") for uid in guessed_ids]
            await bot.send_message(
                chat_id=round.chat_id,
                text=guesses_text(guessed_names, reward=MUSIC_GAME_GUESS_REWARD),
                parse_mode="HTML",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("game.music_game_finalize_send_failed", error=str(exc))

    if author_id is not None:
        await awards.music_author(
            session, author_id, points=MUSIC_GAME_AUTHOR_REWARD, round_id=round.id
        )
        await journal.announce(
            session,
            kind=journal.KIND_EVENT,
            subject_user_id=author_id,
            text=(
                f"🎵 Трек <b>{names.get(author_id, 'участника')}</b> засветился в "
                f"мьюзик-гейме (+{MUSIC_GAME_AUTHOR_REWARD} XP)."
            ),
        )
    for uid in guessed_ids:
        await awards.music_guess(
            session, uid, points=MUSIC_GAME_GUESS_REWARD, round_id=round.id
        )
    log.info(
        "game.music_game_closed",
        round_id=round.id,
        author=author_id,
        guessed=len(guessed_ids),
    )
    return RoundResult(round_id=round.id, author_id=author_id, guessed_ids=guessed_ids)


async def finalize_stale_rounds(
    session: AsyncSession, bot, *, now: datetime
) -> int:
    """Закрыть раунды, чей опрос так и не долетел (рестарт/потеря апдейта).

    Оглашаем автора и награждаем его, но догадок уже не восстановить — раунд
    закрывается без выплат угадавшим.
    """
    cutoff = now - timedelta(minutes=MUSIC_GAME_POLL_MINUTES)
    rows = (
        await session.scalars(
            select(MusicGameRound)
            .where(
                MusicGameRound.closed_at.is_(None),
                MusicGameRound.created_at <= cutoff,
            )
            .order_by(MusicGameRound.id.asc())
        )
    ).all()
    closed = 0
    for row in rows:
        if await finalize_round(session, bot, row, now=now, poll=None) is not None:
            closed += 1
    return closed


# --------------------------------------------------------------------------
# История и job автоматического вызова
# --------------------------------------------------------------------------


async def rounds_history(
    session: AsyncSession, *, limit: int = MUSIC_GAME_HISTORY_LIMIT
) -> list[MusicGameRound]:
    rows = await session.scalars(
        select(MusicGameRound)
        .order_by(MusicGameRound.created_at.desc(), MusicGameRound.id.desc())
        .limit(limit)
    )
    return list(rows)


async def _has_open_round(session: AsyncSession) -> bool:
    found = await session.scalar(
        select(MusicGameRound.id)
        .where(MusicGameRound.closed_at.is_(None))
        .limit(1)
    )
    return found is not None


async def run_music_game_job(
    bot, *, now: datetime | None = None, rng: random.Random | None = None
) -> dict[str, int]:
    """Тик планировщика: закрыть зависшие раунды и, если пора, начать новый.

    Авто-вызов выключен по умолчанию (`game.music.game_enabled`) и срабатывает не
    чаще раза в неделю в заданный день/час. Пока открыт прошлый раунд, новый не
    начинаем — в чате не должно быть двух «угадаек» одновременно.
    """
    from app.db.base import get_sessionmaker

    moment = now or datetime.now(timezone.utc)
    dice = rng or random.Random()
    sm = get_sessionmaker()
    async with sm() as session:
        closed = await finalize_stale_rounds(session, bot, now=moment)
        if not await get_game_music_game_enabled(session):
            return {"closed": closed, "opened": 0}
        if await _has_open_round(session):
            return {"closed": closed, "opened": 0}

        weekday = await get_game_music_game_weekday(session)
        hour = await get_game_music_game_hour(session)
        scheduled = music_service.scheduled_utc(moment, weekday=weekday, hour=hour)
        if scheduled is None:
            return {"closed": closed, "opened": 0}

        # Э18: общий режим активностей — не влезаем в разгар обсуждения.
        from app.services.game import activity

        if await activity.check_window(session, now=moment) != activity.OK:
            return {"closed": closed, "opened": 0}

        last_at = await session.scalar(select(MusicGameRound.created_at).order_by(
            MusicGameRound.created_at.desc(), MusicGameRound.id.desc()
        ).limit(1))
        if last_at is not None:
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=timezone.utc)
            if last_at >= scheduled:
                return {"closed": closed, "opened": 0}

        opened = await open_round(session, bot, now=moment, rng=dice, scheduled_for=scheduled)
        return {"closed": closed, "opened": 1 if opened is not None else 0}
