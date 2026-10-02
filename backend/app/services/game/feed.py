"""Э20: лента активности — «кто что открыл и с кем что случилось».

Пока бот пишет в основной чат, лента нужна редко. Но в двух новых софт-режимах
(«ачивки в приложение» и «всё в приложение», см. `game.config.CHAT_OUTPUT_MODE`)
она становится главной поверхностью: весь анонс уезжает сюда, а в чате — тишина.

Собираем НЕ из отдельной таблицы (миграции в этой партии нет), а из тех данных,
которые и так лежат в БД:

* ачивки — `user_achievements` + каталог в коде (свежие сверху);
* «лох дня» — `loser_rolls` (официальные роллы, без дуэльных прокрутов);
* «чухан недели» — `weekly_chukhan` (только доставленные недели);
* голосовые задания — `game_voice_tasks` (задание и его статус);
* музыка — `music_selections` (выпущенные подборки) и `music_game_rounds`;
* события/праздники/контрабанда/поминовения — `game_journal`.

Э21: у ленты появился ФИЛЬТР ПО ТИПУ — аргумент `kinds` отбирает записи по `kind`.

Так лента работает даже для записей, которые в чат не уходили (muted-режим).

Каждый источник берёт не больше `offset + limit` строк, дальше объединяем и
режем — на маленьком чате это дешевле любых окон и не требует миграций.
"""
from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    GameJournalEntry,
    GameVoiceTask,
    LoserRoll,
    MusicGameRound,
    MusicSelection,
    User,
    UserAchievement,
    WeeklyChukhan,
)
from app.services.game import journal
from app.services.game.achievements_catalog import get as get_achievement
from app.services.game.music import NOTE_PUBLISHED as _MUSIC_PUBLISHED
from app.services.game.voice_catalog import TASKS_BY_CODE as _VOICE_TASKS

log = structlog.get_logger()

# Виды записей ленты. Совпадают с `journal.KIND_*` там, где источник — журнал.
FEED_ACHIEVEMENT = "achievement"
FEED_LOSER = "loser"
FEED_CHUKHAN = "chukhan"
FEED_VOICE = "voice"
FEED_MUSIC = "music"
FEED_MUSIC_GAME = "music_game"

# Ярлыки для фронта: одинаково и в ленте, и в фильтрах.
FEED_ICONS: dict[str, str] = {
    FEED_ACHIEVEMENT: "🏆",
    FEED_LOSER: "👑",
    FEED_CHUKHAN: "🧹",
    FEED_VOICE: "🎙",
    FEED_MUSIC: "🎧",
    FEED_MUSIC_GAME: "🎵",
    journal.KIND_EVENT: "⚡️",
    journal.KIND_HOLIDAY: "🎊",
    journal.KIND_CONTRABAND: "💰",
    journal.KIND_MEMORIAL: "🕯",
}

FEED_TITLES: dict[str, str] = {
    FEED_ACHIEVEMENT: "Ачивка",
    FEED_LOSER: "Лох дня",
    FEED_CHUKHAN: "Чухан недели",
    FEED_VOICE: "Голосовое задание",
    FEED_MUSIC: "Музыка",
    FEED_MUSIC_GAME: "Угадай трек",
    journal.KIND_EVENT: "Событие",
    journal.KIND_HOLIDAY: "Праздник",
    journal.KIND_CONTRABAND: "Контрабанда",
    journal.KIND_MEMORIAL: "Поминовение",
}

# Порядок «от общего к частному» — для фильтров на фронте (чипы).
FEED_KIND_ORDER: tuple[str, ...] = (
    FEED_ACHIEVEMENT,
    FEED_LOSER,
    FEED_CHUKHAN,
    FEED_VOICE,
    FEED_MUSIC,
    FEED_MUSIC_GAME,
    journal.KIND_EVENT,
    journal.KIND_HOLIDAY,
    journal.KIND_CONTRABAND,
    journal.KIND_MEMORIAL,
)

# journal-виды, которые показываем в ленте (буфер ачивок не дублируем — ачивки
# и так приходят из `user_achievements`).
_JOURNAL_KINDS = (
    journal.KIND_EVENT,
    journal.KIND_HOLIDAY,
    journal.KIND_CONTRABAND,
    journal.KIND_MEMORIAL,
)

# Сколько строк максимум берём из каждого источника (защита от O(N) на большом
# чате); на маленьком это с запасом покрывает любую пагинацию.
_MAX_PER_SOURCE = 500


async def build_feed(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    limit: int = 30,
    offset: int = 0,
    kinds: set[str] | None = None,
) -> list[dict]:
    """Собрать объединённую ленту, свежие сверху.

    `user_id` — если задан, лента сужается до записей этого игрока («только мои»).
    `kinds` — если задан, оставляем только записи этих типов (фильтр на фронте).
    Возвращает готовые к сериализации словари (см. `FeedItemOut`).
    """
    depth = min(_MAX_PER_SOURCE, max(limit + offset, limit) + offset)
    items: list[dict] = []
    items.extend(await _achievement_items(session, user_id=user_id, depth=depth))
    items.extend(await _loser_items(session, user_id=user_id, depth=depth))
    items.extend(await _chukhan_items(session, user_id=user_id, depth=depth))
    items.extend(await _voice_items(session, depth=depth))
    items.extend(await _music_items(session, depth=depth))
    items.extend(await _music_game_items(session, depth=depth))
    items.extend(await _journal_items(session, user_id=user_id, depth=depth))

    if kinds:
        items = [it for it in items if it["kind"] in kinds]

    items.sort(key=lambda it: it["at"], reverse=True)
    return items[offset : offset + limit]


async def _achievement_items(
    session: AsyncSession, *, user_id: int | None, depth: int
) -> list[dict]:
    stmt = (
        select(UserAchievement, User)
        .join(User, User.id == UserAchievement.user_id)
        .order_by(UserAchievement.unlocked_at.desc(), UserAchievement.id.desc())
        .limit(depth)
    )
    if user_id is not None:
        stmt = stmt.where(UserAchievement.user_id == user_id)
    rows = (await session.execute(stmt)).all()
    out: list[dict] = []
    for row, user in rows:
        ach = get_achievement(row.code)
        # Кривые/устаревшие коды молча выкидываем — как в профиле.
        if ach is None:
            continue
        out.append(
            _item(
                source="ach",
                row_id=f"ach:{row.id}",
                kind=FEED_ACHIEVEMENT,
                at=row.unlocked_at,
                text=f"«{ach.title}» (+{ach.points} XP)",
                user=user,
            )
        )
    return out


async def _loser_items(
    session: AsyncSession, *, user_id: int | None, depth: int
) -> list[dict]:
    stmt = (
        select(LoserRoll, User)
        .join(User, User.id == LoserRoll.loser_user_id)
        .where(LoserRoll.source != "duel")
        .order_by(LoserRoll.rolled_at.desc(), LoserRoll.id.desc())
        .limit(depth)
    )
    if user_id is not None:
        stmt = stmt.where(LoserRoll.loser_user_id == user_id)
    rows = (await session.execute(stmt)).all()
    out: list[dict] = []
    for roll, user in rows:
        reason = (roll.reason_text or "").strip()
        text = f"«{reason}»" if reason else ""
        out.append(
            _item(
                source="loser",
                row_id=f"loser:{roll.id}",
                kind=FEED_LOSER,
                at=roll.rolled_at,
                text=text,
                user=user,
            )
        )
    return out


async def _chukhan_items(
    session: AsyncSession, *, user_id: int | None, depth: int
) -> list[dict]:
    stmt = (
        select(WeeklyChukhan, User)
        .join(User, User.id == WeeklyChukhan.user_id)
        .where(WeeklyChukhan.posted_at.is_not(None))
        .order_by(WeeklyChukhan.week_start.desc(), WeeklyChukhan.id.desc())
        .limit(depth)
    )
    if user_id is not None:
        stmt = stmt.where(WeeklyChukhan.user_id == user_id)
    rows = (await session.execute(stmt)).all()
    out: list[dict] = []
    for chukhan, user in rows:
        reason = (chukhan.reason_text or "").strip()
        text = f"«{reason}»" if reason else ""
        at = chukhan.posted_at or chukhan.week_start
        out.append(
            _item(
                source="chukhan",
                row_id=f"chukhan:{chukhan.id}",
                kind=FEED_CHUKHAN,
                at=at,
                text=text,
                user=user,
            )
        )
    return out


async def _voice_items(session: AsyncSession, *, depth: int) -> list[dict]:
    """Голосовые задания как записи ленты.

    Записи общие (не «мои»): задание ставится всему чату, у него нет одного
    subject-игрока. Заголовок берём из каталога, чтобы не тащить в ленту полный
    текст с условиями и окном сбора.
    """
    rows = (
        await session.scalars(
            select(GameVoiceTask)
            .order_by(GameVoiceTask.created_at.desc(), GameVoiceTask.id.desc())
            .limit(depth)
        )
    ).all()
    out: list[dict] = []
    for task in rows:
        catalog = _VOICE_TASKS.get(task.code)
        title = catalog.title if catalog else task.code
        reward = int(task.reward or 0)
        closed = task.closed_at is not None
        out.append(
            _item(
                source="voice",
                row_id=f"voice:{task.id}",
                kind=FEED_VOICE,
                at=task.created_at,
                text=(
                    f"«{title}» — +{reward} XP"
                    + (" · задание закрыто" if closed else " · идёт приём")
                ),
                user=None,
            )
        )
    return out


async def _music_items(session: AsyncSession, *, depth: int) -> list[dict]:
    """Выпущенные музыкальные подборки недели."""
    rows = (
        await session.scalars(
            select(MusicSelection)
            .where(MusicSelection.note == _MUSIC_PUBLISHED)
            .order_by(MusicSelection.created_at.desc(), MusicSelection.id.desc())
            .limit(depth)
        )
    ).all()
    return [
        _item(
            source="music",
            row_id=f"music:{sel.id}",
            kind=FEED_MUSIC,
            at=sel.created_at,
            text=f"Подборка недели — {int(sel.track_count or 0)} треков",
            user=None,
        )
        for sel in rows
    ]


async def _music_game_items(session: AsyncSession, *, depth: int) -> list[dict]:
    """Раунды мьюзик-гейма «угадай, кто предложил трек»."""
    rows = (
        await session.scalars(
            select(MusicGameRound)
            .order_by(MusicGameRound.created_at.desc(), MusicGameRound.id.desc())
            .limit(depth)
        )
    ).all()
    out: list[dict] = []
    for round_ in rows:
        closed = round_.closed_at is not None
        out.append(
            _item(
                source="music_game",
                row_id=f"music_game:{round_.id}",
                kind=FEED_MUSIC_GAME,
                at=round_.created_at,
                text=(
                    "Кто предложил трек?"
                    + (" · раунд закрыт" if closed else " · идёт голосование")
                ),
                user=None,
            )
        )
    return out


async def _journal_items(
    session: AsyncSession, *, user_id: int | None, depth: int
) -> list[dict]:
    stmt = (
        select(GameJournalEntry)
        .where(GameJournalEntry.kind.in_(_JOURNAL_KINDS))
        .order_by(GameJournalEntry.created_at.desc(), GameJournalEntry.id.desc())
        .limit(depth)
    )
    if user_id is not None:
        stmt = stmt.where(GameJournalEntry.subject_user_id == user_id)
    rows = list(await session.scalars(stmt))
    users: dict[int, User] = {}
    out: list[dict] = []
    for entry in rows:
        user = None
        if entry.subject_user_id is not None:
            if entry.subject_user_id not in users:
                fetched = await session.get(User, entry.subject_user_id)
                if fetched is not None:
                    users[entry.subject_user_id] = fetched
            user = users.get(entry.subject_user_id)
        out.append(
            _item(
                source="journal",
                row_id=f"journal:{entry.id}",
                kind=entry.kind,
                at=entry.created_at,
                text=entry.text or "",
                user=user,
            )
        )
    return out


def _item(
    *,
    source: str,
    row_id: str,
    kind: str,
    at,
    text: str,
    user: User | None,
) -> dict:
    return {
        "id": row_id,
        "source": source,
        "kind": kind,
        "icon": FEED_ICONS.get(kind, "📌"),
        "title": FEED_TITLES.get(kind, "Событие"),
        "text": text,
        "at": at,
        "user_id": user.id if user is not None else None,
        "user_name": user.display_name if user is not None else None,
        "user_telegram_id": user.telegram_id if user is not None else None,
        "avatar_url": (
            (getattr(user, "avatar_manual_url", None) or getattr(user, "avatar_url", None))
            if user is not None
            else None
        ),
    }
