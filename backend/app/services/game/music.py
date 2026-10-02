"""GHG10 Э15: музыкальная предложка (GHG8 H.7).

Участники кидают треки боту В ЛИЧКУ в течение недели; раз в неделю (день и час
настраиваются) бот вываливает подборку 4–10 треков с дежурным сообщением. Треки
хранятся ТОЛЬКО как ссылка или Telegram `file_id` — файлы физически не держим
(слабый хост).

Три правила из исходного ТЗ H.7, которые держим буквально:

1. **Память об использованных.** Трек со статусом `published` в следующую
   подборку не попадёт (это и есть память).
2. **Недобор.** Если к моменту публикации треков меньше минимума — бот зовёт
   помочь и повторяет попытку через `MUSIC_RETRY_HOURS` (3–6 ч), а не сыплет
   проверками.
3. **Слабый хост.** Никаких поллингов в цикле: job тикает редко и сам решает
   «пора/не пора» по расписанию и последней попытке.

Сервис разделён как остальные: чистая логика (расписание, текст, выбор) —
отдельно; I/O — тонким слоем.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import MusicSelection, MusicTrack, MusicTrackLike, User
from app.services.admin_config import (
    get_game_music_attribute,
    get_game_music_enabled,
    get_game_music_hour,
    get_game_music_weekday,
)
from app.services.game.config import (
    MUSIC_MAX_TITLE,
    MUSIC_MAX_TRACKS,
    MUSIC_MAX_URL,
    MUSIC_MIN_TRACKS,
    MUSIC_PER_USER_WEEKLY,
    MUSIC_RETRY_HOURS,
    MUSIC_TOP_TRACKS_LIMIT,
    MUSIC_TOP_WINDOW_DAYS,
    VOICE_TZ_OFFSET_HOURS,
)

log = structlog.get_logger()

# Статусы приёма трека.
OK = "ok"
UNKNOWN_USER = "unknown_user"
LIMIT = "limit"
DUPLICATE = "duplicate"
BAD = "bad"

STATUS_POOL = "pool"
STATUS_PUBLISHED = "published"
STATUS_REMOVED = "removed"

NOTE_PUBLISHED = "published"
NOTE_SHORTFALL = "shortfall"

_LINK_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


# --------------------------------------------------------------------------
# Чистая логика
# --------------------------------------------------------------------------


def looks_like_link(text: str | None) -> bool:
    """Ссылка ли это. Чистая функция (тесты)."""
    if not text:
        return False
    return bool(_LINK_RE.match(text.strip()))


def local_moment(now: datetime) -> datetime:
    """Локальное (для чата) время. Чистая функция."""
    return now.astimezone(timezone.utc) + timedelta(hours=VOICE_TZ_OFFSET_HOURS)


def scheduled_utc(now: datetime, *, weekday: int, hour: int) -> datetime | None:
    """Момент публикации на этой ISO-неделе в UTC. `None` — окно ещё не открылось.

    Чистая функция. Считаем по локальному времени чата: «вторник 12:00» значит
    вторник 12:00 у участников, а не в UTC.
    """
    local = local_moment(now)
    monday = local.date() - timedelta(days=local.weekday())
    scheduled_local = datetime.combine(
        monday + timedelta(days=weekday), time(hour, 0), tzinfo=timezone.utc
    )
    if scheduled_local > local:
        return None
    return scheduled_local - timedelta(hours=VOICE_TZ_OFFSET_HOURS)


def build_publication_lines(
    tracks: list[MusicTrack], names: dict[int, str], *, attribute: bool
) -> list[str]:
    """Строки подборки. Чистая функция (тесты).

    Для ссылочных треков показываем ссылку; для аудио-файлов — только подпись
    (сам файл уезжает отдельным сообщением, `file_id` в строку не влезет).
    """
    lines: list[str] = []
    for index, track in enumerate(tracks, start=1):
        title = track.title or track.performer or track.url or "трек"
        line = f"{index}. <b>{title}</b>"
        if track.kind == "link" and track.url:
            line += f" — {track.url}"
        if attribute:
            name = names.get(track.user_id)
            if name:
                line += f" <i>(от {name})</i>"
        lines.append(line)
    return lines


def pick_for_publication(
    tracks: list[MusicTrack], *, rng: random.Random, limit: int = MUSIC_MAX_TRACKS
) -> list[MusicTrack]:
    """Что попадёт в подборку: не больше `limit`, случайная выборка, но стабильный
    порядок по `added_at` (раньше предложил — раньше в подборке). Чистая функция."""
    if len(tracks) <= limit:
        return list(tracks)
    chosen = rng.sample(tracks, limit)
    return sorted(chosen, key=lambda t: (t.added_at, t.id))


def publication_header(*, count: int) -> str:
    return f"🎧 <b>Подборка недели</b> — {count} треков от наших:"


def shortfall_text(*, have: int, need: int) -> str:
    return (
        f"🎧 Подборка не набралась: есть {have} из минимум {need}. "
        "Кидайте треки боту в личку — соберём и выложим."
    )


# --------------------------------------------------------------------------
# Приём треков
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackResult:
    status: str
    week_count: int = 0


def _iso_week_start(day: datetime) -> datetime:
    """Начало ISO-недели (понедельник 00:00 UTC) для момента. Чистая функция."""
    moment = day.astimezone(timezone.utc)
    monday = moment.date() - timedelta(days=moment.weekday())
    return datetime.combine(monday, time.min, tzinfo=timezone.utc)


async def weekly_count(session: AsyncSession, user_id: int, *, at: datetime) -> int:
    """Сколько треков юзер прислал на текущей ISO-неделе (без снятых админом)."""
    count = await session.scalar(
        select(func.count())
        .select_from(MusicTrack)
        .where(
            MusicTrack.user_id == user_id,
            MusicTrack.added_at >= _iso_week_start(at),
            MusicTrack.status != STATUS_REMOVED,
        )
    )
    return int(count or 0)


async def my_week_tracks(
    session: AsyncSession, user_id: int, *, at: datetime
) -> list[MusicTrack]:
    """Треки, сданные участником на текущей ISO-неделе (для мини-аппа)."""
    rows = await session.scalars(
        select(MusicTrack)
        .where(
            MusicTrack.user_id == user_id,
            MusicTrack.added_at >= _iso_week_start(at),
            MusicTrack.status != STATUS_REMOVED,
        )
        .order_by(MusicTrack.added_at.desc(), MusicTrack.id.desc())
    )
    return list(rows)


async def published_selections(
    session: AsyncSession, *, limit: int = 10
) -> list[MusicSelection]:
    """Только состоявшиеся подборки (без недоборов) — для участника."""
    rows = await session.scalars(
        select(MusicSelection)
        .where(MusicSelection.note == NOTE_PUBLISHED)
        .order_by(MusicSelection.created_at.desc(), MusicSelection.id.desc())
        .limit(limit)
    )
    return list(rows)


# --------------------------------------------------------------------------
# Э17: лайки трекам подборки и топ недели (задел H.8)
# --------------------------------------------------------------------------

# Коды результата лайка (как у приёма треков — сервис не бросает, а возвращает).
LIKE_OK = "ok"
LIKE_NOT_PUBLISHED = "not_published"


@dataclass(frozen=True)
class LikeResult:
    """Итог переключения лайка: состояние + сколько лайков у трека сейчас."""

    status: str
    liked: bool = False
    likes: int = 0


async def latest_published_selection(
    session: AsyncSession,
) -> MusicSelection | None:
    """Свежая выпущенная подборка — то, что показывает мини-апп."""
    return await session.scalar(
        select(MusicSelection)
        .where(MusicSelection.note == NOTE_PUBLISHED)
        .order_by(MusicSelection.created_at.desc(), MusicSelection.id.desc())
        .limit(1)
    )


async def selection_tracks(
    session: AsyncSession, selection_id: int
) -> list[MusicTrack]:
    """Треки одной подборки. Порядок — по id: внутри подборки он и есть порядок
    показа (строки подборки были отсортированы по `added_at`)."""
    rows = await session.scalars(
        select(MusicTrack)
        .where(MusicTrack.selection_id == selection_id)
        .order_by(MusicTrack.id.asc())
    )
    return list(rows)


async def like_counts(
    session: AsyncSession, track_ids: list[int]
) -> dict[int, int]:
    """Сколько лайков у каждого из треков — один SELECT (без N+1)."""
    if not track_ids:
        return {}
    rows = (
        await session.execute(
            select(MusicTrackLike.track_id, func.count())
            .where(MusicTrackLike.track_id.in_(track_ids))
            .group_by(MusicTrackLike.track_id)
        )
    ).all()
    return {int(tid): int(count) for tid, count in rows}


async def liked_track_ids(
    session: AsyncSession, user_id: int, track_ids: list[int]
) -> set[int]:
    """Какие из треков уже лайкнул этот участник — один SELECT."""
    if not track_ids:
        return set()
    rows = await session.scalars(
        select(MusicTrackLike.track_id).where(
            MusicTrackLike.user_id == user_id,
            MusicTrackLike.track_id.in_(track_ids),
        )
    )
    return {int(tid) for tid in rows.all()}


async def toggle_like(
    session: AsyncSession, *, user_id: int, track_id: int
) -> LikeResult:
    """Поставить/снять лайк треку из ВЫПУЩЕННОЙ подборки.

    Идемпотентность держится на `UniqueConstraint`: повторный тап «поставить»
    создаёт вторую строку с ошибкой целостности, поэтому сначала ищем уже
    имеющуюся запись. Лайкнуть можно только трек со статусом `published` —
    треки из пула до подборки не показываем и не оцениваем.
    """
    track = await session.get(MusicTrack, track_id)
    if track is None or track.status != STATUS_PUBLISHED:
        return LikeResult(LIKE_NOT_PUBLISHED)

    existing = await session.scalar(
        select(MusicTrackLike).where(
            MusicTrackLike.user_id == user_id,
            MusicTrackLike.track_id == track_id,
        )
    )
    liked: bool
    if existing is not None:
        await session.delete(existing)
        liked = False
    else:
        session.add(MusicTrackLike(user_id=user_id, track_id=track_id))
        liked = True
    await session.commit()
    likes = await session.scalar(
        select(func.count())
        .select_from(MusicTrackLike)
        .where(MusicTrackLike.track_id == track_id)
    )
    return LikeResult(LIKE_OK, liked=liked, likes=int(likes or 0))


async def top_tracks(
    session: AsyncSession,
    *,
    since: datetime,
    limit: int = MUSIC_TOP_TRACKS_LIMIT,
) -> list[tuple[MusicTrack, int]]:
    """Топ треков недели по лайкам (только выпущенные, свежие окном `since`)."""
    rows = (
        await session.execute(
            select(MusicTrack, func.count(MusicTrackLike.id))
            .join(MusicTrackLike, MusicTrackLike.track_id == MusicTrack.id)
            .where(
                MusicTrack.status == STATUS_PUBLISHED,
                MusicTrackLike.created_at >= since,
            )
            .group_by(MusicTrack.id)
            .order_by(
                func.count(MusicTrackLike.id).desc(),
                MusicTrack.id.asc(),
            )
            .limit(limit)
        )
    ).all()
    return [(track, int(count)) for track, count in rows]


def top_window_start(at: datetime) -> datetime:
    """Начало окна «недели» топа: `MUSIC_TOP_WINDOW_DAYS` дней назад. Чистая."""
    return at.astimezone(timezone.utc) - timedelta(days=MUSIC_TOP_WINDOW_DAYS)


async def add_track(
    session: AsyncSession,
    *,
    telegram_id: int,
    kind: str,
    file_id: str | None = None,
    url: str | None = None,
    title: str | None = None,
    performer: str | None = None,
    duration: int | None = None,
    at: datetime | None = None,
) -> TrackResult:
    """Принять трек из лички. Никогда не бросает — статус в результате."""
    moment = at or datetime.now(timezone.utc)
    user_id = await session.scalar(
        select(User.id).where(User.telegram_id == telegram_id)
    )
    if user_id is None:
        return TrackResult(UNKNOWN_USER)
    user_id = int(user_id)

    if kind == "link":
        if not looks_like_link(url):
            return TrackResult(BAD)
    elif kind == "audio":
        if not file_id:
            return TrackResult(BAD)
    else:
        return TrackResult(BAD)

    if await weekly_count(session, user_id, at=moment) >= MUSIC_PER_USER_WEEKLY:
        return TrackResult(LIMIT)

    # Дубль в пуле (та же ссылка или тот же файл) — не принимаем.
    if kind == "link" and url is not None:
        dup = await session.scalar(
            select(MusicTrack.id)
            .where(
                MusicTrack.user_id == user_id,
                MusicTrack.url == url,
                MusicTrack.status != STATUS_REMOVED,
            )
            .limit(1)
        )
        if dup is not None:
            return TrackResult(DUPLICATE)
    if kind == "audio" and file_id is not None:
        dup = await session.scalar(
            select(MusicTrack.id)
            .where(
                MusicTrack.user_id == user_id,
                MusicTrack.file_id == file_id,
                MusicTrack.status != STATUS_REMOVED,
            )
            .limit(1)
        )
        if dup is not None:
            return TrackResult(DUPLICATE)

    session.add(
        MusicTrack(
            user_id=user_id,
            kind=kind,
            file_id=file_id,
            url=(url or None)[:MUSIC_MAX_URL] if url else None,
            title=(title or None)[:MUSIC_MAX_TITLE] if title else None,
            performer=(performer or None)[:MUSIC_MAX_TITLE] if performer else None,
            duration=duration,
            added_at=moment,
            status=STATUS_POOL,
        )
    )
    await session.commit()
    count = await weekly_count(session, user_id, at=moment)
    log.info("game.music_track_added", user_id=user_id, kind=kind)
    return TrackResult(OK, week_count=count)


async def pool_tracks(session: AsyncSession) -> list[MusicTrack]:
    """Треки, ждущие подборки, в порядке поступления."""
    rows = await session.scalars(
        select(MusicTrack)
        .where(MusicTrack.status == STATUS_POOL)
        .order_by(MusicTrack.added_at.asc(), MusicTrack.id.asc())
    )
    return list(rows)


async def _names(session: AsyncSession, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(User.id, User.display_name).where(User.id.in_(ids))
    )
    return {int(uid): name for uid, name in rows.all()}


# --------------------------------------------------------------------------
# Публикация
# --------------------------------------------------------------------------


async def publish(
    session: AsyncSession, bot, *, now: datetime, rng: random.Random
) -> MusicSelection | None:
    """Собрать и выложить подборку. `None` — публиковать нечего или TG не принял."""
    # Э20: режим «всё в приложение» — подборку в чат не выкладываем.
    from app.services.game import chat_mode

    if await chat_mode.chat_all_silent(session):
        return None
    tracks = await pool_tracks(session)
    if len(tracks) < MUSIC_MIN_TRACKS:
        return None
    chosen = pick_for_publication(tracks, rng=rng)
    names = await _names(session, [t.user_id for t in chosen])
    attribute = await get_game_music_attribute(session)

    settings = get_settings()
    chat_id = settings.group_chat_id
    if not chat_id or bot is None:
        return None

    selection = MusicSelection(
        chat_id=chat_id, track_count=len(chosen), note=NOTE_PUBLISHED
    )
    session.add(selection)
    await session.flush()  # нужен id для связи треков

    lines = build_publication_lines(chosen, names, attribute=attribute)
    header = publication_header(count=len(chosen))
    try:
        message = await bot.send_message(
            chat_id=chat_id,
            text=header + "\n" + "\n".join(lines),
            parse_mode="HTML",
        )
        selection.tg_message_id = message.message_id
        # Аудио-файлы доигрываем отдельными сообщениями: ссылки в строке нет,
        # а `file_id` — единственное, что у нас есть.
        for index, track in enumerate(chosen, start=1):
            if track.kind != "audio" or not track.file_id:
                continue
            caption = f"№{index} — <b>{track.title or track.performer or 'трек'}</b>"
            if attribute and names.get(track.user_id):
                caption += f" <i>(от {names[track.user_id]})</i>"
            try:
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=track.file_id,
                    caption=caption,
                    parse_mode="HTML",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("game.music_audio_send_failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.warning("game.music_publish_failed", error=str(exc))
        await session.rollback()
        return None

    for track in chosen:
        track.status = STATUS_PUBLISHED
        track.selection_id = selection.id
    await session.commit()
    log.info("game.music_published", tracks=len(chosen), selection_id=selection.id)

    # Э17: трек ушёл в подборку — автору идёт «Диджей недели». Зовём ПОСЛЕ
    # commit'а (правило awards): только теперь трек реально числится выпущенным.
    from app.services.game import awards  # ленивый импорт: цикл модулей

    for track in chosen:
        await awards.music_published(session, track.user_id, track_id=track.id)
    return selection


async def _record_shortfall(
    session: AsyncSession, bot, *, now: datetime, have: int
) -> None:
    """Записать неудачную попытку и позвать помочь. Повтор — через retry_hours."""
    settings = get_settings()
    chat_id = settings.group_chat_id
    selection = MusicSelection(
        chat_id=chat_id or 0, track_count=have, note=NOTE_SHORTFALL
    )
    session.add(selection)
    await session.commit()
    from app.services.game import chat_mode

    if chat_id and bot is not None and not await chat_mode.chat_all_silent(session):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=shortfall_text(have=have, need=MUSIC_MIN_TRACKS),
                parse_mode="HTML",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("game.music_shortfall_send_failed", error=str(exc))


async def run_music_job(
    bot, *, now: datetime | None = None, rng: random.Random | None = None
) -> dict[str, int]:
    """Тик планировщика: если окно публикации открыто и пора — выложить подборку."""
    from app.db.base import get_sessionmaker

    moment = now or datetime.now(timezone.utc)
    dice = rng or random.Random()
    sm = get_sessionmaker()
    async with sm() as session:
        if not await get_game_music_enabled(session):
            return {"published": 0}
        weekday = await get_game_music_weekday(session)
        hour = await get_game_music_hour(session)
        scheduled = scheduled_utc(moment, weekday=weekday, hour=hour)
        if scheduled is None:
            return {"published": 0}  # окно этой недели ещё не открылось

        last = await session.scalar(
            select(MusicSelection)
            .order_by(MusicSelection.created_at.desc(), MusicSelection.id.desc())
            .limit(1)
        )
        if last is not None:
            last_at = last.created_at
            if last_at is not None and last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=timezone.utc)
            if last_at is not None and last_at >= scheduled:
                if last.note == NOTE_PUBLISHED:
                    return {"published": 0}  # на этой неделе уже выложили
                # Недобор: повторную попытку делаем не раньше retry_hours.
                if moment - last_at < timedelta(hours=MUSIC_RETRY_HOURS):
                    return {"published": 0}

        tracks = await pool_tracks(session)
        if len(tracks) < MUSIC_MIN_TRACKS:
            await _record_shortfall(session, bot, now=moment, have=len(tracks))
            return {"published": 0}
        selection = await publish(session, bot, now=moment, rng=dice)
        return {"published": 1 if selection is not None else 0}


async def selections_history(
    session: AsyncSession, *, limit: int = 20
) -> list[MusicSelection]:
    """История подборок и попыток (для админ-экрана)."""
    rows = await session.scalars(
        select(MusicSelection)
        .order_by(MusicSelection.created_at.desc(), MusicSelection.id.desc())
        .limit(limit)
    )
    return list(rows)
