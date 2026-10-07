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

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    GameJournalEntry,
    GamePrompt,
    GameVoiceTask,
    LoserRoll,
    MusicGameRound,
    MusicSelection,
    User,
    UserAchievement,
    WeeklyChukhan,
)
from app.services.game import activity, journal
from app.services.game.achievements_catalog import get as get_achievement
from app.services.game.config import (
    MUSIC_GAME_AUTHOR_REWARD,
    MUSIC_GAME_GUESS_REWARD,
)
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
# GHG11: активность механик без своей таблицы (совет, червь, реакции, номинации).
FEED_FEATURE = "feature"

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
    FEED_FEATURE: "✨",
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
    FEED_FEATURE: "Активность",
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
    FEED_FEATURE,
)

# GHG11(5): виды с ОДНИМ участником-субъектом (лох/чухан/активность фичи). Им
# тоже даём миниатюру-подложку, чтобы у каждого блока ленты был одинаковый
# быстрый обзор «кто это», а не только у голосовых/музыки.
_SINGLE_PARTICIPANT_KINDS = (FEED_LOSER, FEED_CHUKHAN, FEED_FEATURE)

# journal-виды, которые показываем в ленте (буфер ачивок не дублируем — ачивки
# и так приходят из `user_achievements`).
_JOURNAL_KINDS = (
    journal.KIND_EVENT,
    journal.KIND_HOLIDAY,
    journal.KIND_CONTRABAND,
    journal.KIND_MEMORIAL,
    FEED_FEATURE,
)

# Сколько строк максимум берём из каждого источника (защита от O(N) на большом
# чате); на маленьком это с запасом покрывает любую пагинацию.
_MAX_PER_SOURCE = 500

# GHG11(8): насколько далеко от создания промпта может лежать его анонс в ленте.
# Промпт и обе записи журнала создаются в ОДНОМ тике планировщика, поэтому
# реальный разрыв — миллисекунды. Окно нужно как страховка и главное — чтобы НЕ
# привязать к открытому промпту старый анонс с тем же текстом (кулдаун 7 дней).
_ACTIVITY_MATCH_WINDOW = timedelta(minutes=10)


async def build_feed(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    viewer_id: int | None = None,
    limit: int = 30,
    offset: int = 0,
    kinds: set[str] | None = None,
    muted_ids: set[int] | None = None,
) -> list[dict]:
    """Собрать объединённую ленту, свежие сверху.

    `user_id` — если задан, лента сужается до записей этого игрока («только мои»).
    `viewer_id` — кто смотрит: его личные «скрыто у себя» не показываем (GHG11).
    `kinds` — если задан, оставляем только записи этих типов (фильтр на фронте).
    `muted_ids` — GHG11(7): участники, чьи события смотрящий скрыл у себя в ленте
    («по участникам»). Свои события из ленты не выкидываем никогда — иначе
    лента «сломается» (свою галочку отключить нельзя).
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

    # GHG11(7): персональный фильтр «по участникам». Записи без субъекта
    # (голосовые задания, подборки, муз-гейм) и свои собственные остаются.
    if muted_ids:
        items = [
            it
            for it in items
            if it["user_id"] is None
            or it["user_id"] not in muted_ids
            or it["user_id"] == viewer_id
        ]

    # GHG11: удалённые админом (для всех) и «скрытые у себя» (для смотрящего).
    from app.services.game import feed_moderation

    removed = await feed_moderation.deleted_item_ids(session)
    if viewer_id is not None:
        removed |= await feed_moderation.hidden_item_ids(session, viewer_id)
    if removed:
        items = [it for it in items if it["id"] not in removed]

    # GHG11: плашки званий над головой (сегодня лох/чухан/червь) — одним
    # проходом на всю ленту, дальше просто раскидываем по строкам.
    from app.services.game import today_titles

    badges = await today_titles.badge_map(session)
    for it in items:
        uid = it.get("user_id")
        it["badges"] = badges.get(uid, []) if uid is not None else []

    items.sort(key=lambda it: it["at"], reverse=True)
    page = items[offset : offset + limit]
    # Э22: тяжёлые подробности — только для страницы. Лайки «мои» считаем по
    # смотрящему (`viewer_id`), а не по фильтру ленты (`user_id`).
    await _attach_details(session, page, user_id=viewer_id if viewer_id is not None else user_id)
    return page


def _as_utc(moment: datetime | None) -> datetime | None:
    """Наивное время из БД считаем UTC (сравниваем только с UTC-моментами)."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


async def _open_prompts(
    session: AsyncSession | None, *, now: datetime
) -> list[GamePrompt]:
    """Открытые промпты (случайные события), ещё ждущие ответа.

    `session=None` — так `_attach_details` зовут тесты (подменяют сервисы и БД
    не используют): активностей тогда просто нет.
    """
    if session is None:
        return []
    rows = await session.scalars(
        select(GamePrompt).where(
            GamePrompt.closed_at.is_(None),
            GamePrompt.expires_at > now,
        )
    )
    return list(rows)


def match_prompt_activity(
    item: dict,
    prompts: list[GamePrompt],
    *,
    window: timedelta = _ACTIVITY_MATCH_WINDOW,
) -> GamePrompt | None:
    """Найти промпт, чей анонс — эта запись ленты. Чистая функция.

    Прямой связи «запись журнала → промпт» в БД нет, но анонс публикует сам
    промпт своим текстом и в тот же тик планировщика — поэтому сверяем текст и
    близость по времени. Окно отсекает старые анонсы того же текста, поэтому
    участие доступно ровно у свежего задания, а не у прошлых.
    """
    if item.get("kind") != journal.KIND_EVENT:
        return None
    text = (item.get("text") or "").strip()
    at = _as_utc(item.get("at"))
    if not text or at is None:
        return None
    best: GamePrompt | None = None
    for prompt in prompts:
        if (prompt.text or "").strip() != text:
            continue
        created = _as_utc(prompt.created_at)
        if created is None or abs((at - created).total_seconds()) > window.total_seconds():
            continue
        if best is None or created > _as_utc(best.created_at):
            best = prompt
    return best


def activity_detail(prompt: GamePrompt, *, user_id: int | None) -> dict:
    """Интерфейс участия в задании для карточки ленты: варианты и/или ввод."""
    options, needs_text = activity.split_activity_options(list(prompt.answers or []))
    return {
        "id": prompt.id,
        "code": prompt.code,
        "options": [{"label": label, "xp": xp} for label, xp in options],
        "needs_text": needs_text,
        "expires_at": prompt.expires_at,
        "answered_by_me": user_id is not None and prompt.winner_user_id == user_id,
    }


async def _attach_details(
    session: AsyncSession, items: list[dict], *, user_id: int | None
) -> None:
    """Дотянуть подробности для раскрывающихся карточек ленты (Э22).

    Список сдач голосового и треки подборки — отдельные выборки, поэтому делаем
    их лишь для тех строк, что реально попали на экран, а не для всего источника.
    """
    from app.services.game import music, voice

    # GHG11(8): открытые задания-призывы нужны только если на странице есть их
    # анонсы (журнальные «event») — иначе лишний SELECT на каждую ленту.
    open_prompts: list[GamePrompt] = []
    if any(it.get("kind") == journal.KIND_EVENT for it in items):
        open_prompts = await _open_prompts(session, now=datetime.now(timezone.utc))

    for it in items:
        row_id = it["id"]
        detail = dict(it.get("detail") or {})
        # GHG11(5): лох/чухан/активность фичи — миниатюра-субъект (та же форма,
        # что у музыки/голосовых: без XP/лайков → аватарка без бейджа).
        if it["kind"] in _SINGLE_PARTICIPANT_KINDS and not detail.get("participants"):
            uid = it.get("user_id")
            if uid is not None:
                detail["participants"] = [
                    {
                        "user_id": uid,
                        "user_name": it.get("user_name"),
                        "avatar_url": it.get("avatar_url"),
                        "xp": 0,
                        "likes": 0,
                    }
                ]
        if row_id.startswith("voice:"):
            task_id = int(row_id.split(":", 1)[1])
            subs = await voice._submissions(session, task_id)
            names = await voice._user_names(session, [s.user_id for s in subs])
            sub_ids = [s.id for s in subs]
            likes = await voice.like_counts(session, sub_ids)
            mine = (
                await voice.liked_ids(session, user_id, sub_ids)
                if user_id is not None
                else set()
            )
            # GHG11(4): сколько XP получил каждый — для миниатюр под заданием.
            # `all` — награда каждому; `first_only` — только первому сдавшему.
            reward = int((it.get("detail") or {}).get("reward") or 0)
            mode = await voice.get_task_mode(session, task_id)
            avatars = await _submission_avatars(session, [s.user_id for s in subs])
            detail["submissions"] = [
                {
                    "id": s.id,
                    "user_id": s.user_id,
                    "user_name": names.get(s.user_id),
                    "avatar_url": avatars.get(s.user_id),
                    "duration": s.duration,
                    "likes": likes.get(s.id, 0),
                    "liked": s.id in mine,
                    "xp": (
                        reward
                        if mode != voice.MODE_FIRST_ONLY or index == 0
                        else 0
                    ),
                }
                for index, s in enumerate(subs)
            ]
        elif row_id.startswith("music:"):
            sel_id = int(row_id.split(":", 1)[1])
            tracks = await music.selection_tracks(session, sel_id)
            ids = [t.id for t in tracks]
            likes = await music.like_counts(session, ids)
            mine = (
                await music.liked_track_ids(session, user_id, ids)
                if user_id is not None
                else set()
            )
            meta = await _user_meta(session, [t.user_id for t in tracks])
            detail["tracks"] = [
                {
                    "id": t.id,
                    "kind": t.kind,
                    "title": t.title,
                    "performer": t.performer,
                    "url": t.url,
                    "likes": likes.get(t.id, 0),
                    "liked": t.id in mine,
                    "user_id": t.user_id,
                    "user_name": meta.get(t.user_id, {}).get("user_name"),
                    "avatar_url": meta.get(t.user_id, {}).get("avatar_url"),
                }
                for t in tracks
            ]
            # GHG11(4): компактные миниатюры участников — владельцы треков этой
            # подборки, с суммой лайков по их трекам.
            detail["participants"] = _aggregate_participants(tracks, meta, likes)
        elif row_id.startswith("music_game:"):
            round_id = int(row_id.split(":", 1)[1])
            round_ = await session.get(MusicGameRound, round_id)
            if round_ is not None:
                detail = await _music_game_detail(session, round_, detail)
        # GHG11(8): анонс задания — сам себе форма участия. Если это свежий
        # призыв (открытый промпт), в карточку кладём кнопки/поле ввода, чтобы
        # ответить прямо из ленты, не уходя в чат.
        if it.get("kind") == journal.KIND_EVENT and open_prompts:
            prompt = match_prompt_activity(it, open_prompts)
            if prompt is not None:
                detail["activity"] = activity_detail(prompt, user_id=user_id)
        it["detail"] = detail or None


async def _submission_avatars(
    session: AsyncSession, user_ids: list[int]
) -> dict[int, str | None]:
    """user_id → аватарка (мануальная или TG) одним SELECT — для миниатюр."""
    if not user_ids:
        return {}
    rows = await session.execute(
        select(User.id, User.avatar_manual_url, User.avatar_url).where(
            User.id.in_(set(user_ids))
        )
    )
    return {int(uid): (manual or tg) for uid, manual, tg in rows.all()}


async def _user_meta(
    session: AsyncSession, user_ids: list[int]
) -> dict[int, dict]:
    """user_id → {user_name, avatar_url} одним SELECT — для миниатюр."""
    if not user_ids:
        return {}
    rows = await session.execute(
        select(User.id, User.display_name, User.avatar_manual_url, User.avatar_url).where(
            User.id.in_(set(user_ids))
        )
    )
    return {
        int(uid): {"user_name": name, "avatar_url": manual or tg}
        for uid, name, manual, tg in rows.all()
    }


def _aggregate_participants(tracks: list, meta: dict[int, dict], likes: dict[int, int]) -> list[dict]:
    """Участники подборки: по одному элементу на владельца треков + лайки.

    Миниатюры в ленте должны быть компактными, поэтому один владелец — один
    элемент (а не строка на трек); лайки его треков суммируются.
    """
    agg: dict[int, dict] = {}
    for t in tracks:
        entry = agg.setdefault(
            t.user_id,
            {
                "user_id": t.user_id,
                "user_name": meta.get(t.user_id, {}).get("user_name"),
                "avatar_url": meta.get(t.user_id, {}).get("avatar_url"),
                "xp": 0,
                "likes": 0,
            },
        )
        entry["likes"] += int(likes.get(t.id, 0))
    return list(agg.values())


async def _music_game_detail(
    session: AsyncSession, round_, detail: dict
) -> dict:
    """Подробности раунда мьюзик-гейма: автор + угадавшие с XP и лайки трека.

    `participants` — те, кто получил опыт: автор трека (+AUTHOR_REWARD) и
    угадавшие (+GUESS_REWARD). `track_likes` — лайки загаданного трека.
    """
    from app.services.game import music as _music

    ids: list[int] = []
    if round_.correct_user_id is not None:
        ids.append(int(round_.correct_user_id))
    ids.extend(int(uid) for uid in (round_.correct_voter_ids or []))
    meta = await _user_meta(session, ids)
    participants: list[dict] = []
    if round_.correct_user_id is not None:
        cid = int(round_.correct_user_id)
        participants.append(
            {
                "user_id": cid,
                "user_name": meta.get(cid, {}).get("user_name"),
                "avatar_url": meta.get(cid, {}).get("avatar_url"),
                "xp": MUSIC_GAME_AUTHOR_REWARD,
                "likes": 0,
                "role": "author",
            }
        )
    for uid in round_.correct_voter_ids or []:
        uid = int(uid)
        participants.append(
            {
                "user_id": uid,
                "user_name": meta.get(uid, {}).get("user_name"),
                "avatar_url": meta.get(uid, {}).get("avatar_url"),
                "xp": MUSIC_GAME_GUESS_REWARD,
                "likes": 0,
                "role": "guesser",
            }
        )
    detail["participants"] = participants
    if round_.track_id is not None:
        counts = await _music.like_counts(session, [int(round_.track_id)])
        detail["track_likes"] = counts.get(int(round_.track_id), 0)
    return detail


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
                detail={
                    "code": ach.code,
                    "description": ach.description,
                    "points": ach.points,
                },
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
                detail={"reason": reason},
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
                detail={"reason": reason, "week_start": chukhan.week_start},
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
                detail={
                    "task_id": task.id,
                    "title": title,
                    "condition": task.text,
                    "opened_at": task.created_at,
                    "closed_at": task.closed_at,
                    "expires_at": task.expires_at,
                    "reward": reward,
                    "closed": closed,
                },
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
            detail={"selection_id": sel.id, "track_count": int(sel.track_count or 0)},
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
                detail={"closed_at": round_.closed_at, "closed": closed},
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
    detail: dict | None = None,
) -> dict:
    return {
        "id": row_id,
        "source": source,
        "kind": kind,
        "icon": FEED_ICONS.get(kind, "📌"),
        "title": FEED_TITLES.get(kind, "Событие"),
        "text": text,
        "at": at,
        "detail": detail,
        "badges": [],
        "user_id": user.id if user is not None else None,
        "user_name": user.display_name if user is not None else None,
        "user_telegram_id": user.telegram_id if user is not None else None,
        "avatar_url": (
            (getattr(user, "avatar_manual_url", None) or getattr(user, "avatar_url", None))
            if user is not None
            else None
        ),
    }
