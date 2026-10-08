"""GHG10 Э7: телеметрия мемов → мем-ачивки.

Четыре ачивки задания держатся на одном факте: «что случилось с конкретным
постом». Здесь этот факт собирается и превращается в вызовы фасада
(`awards.meme_all_reacted` / `awards.meme_reactions` / `awards.dead_post`):

- **отклик** — живая реакция, reply на пост или сообщение в чате сразу под
  постом (в пределах окна `MEME_REACTION_WINDOW_MIN`);
- **окно реакции** решает «Мемолога»: нужны отклики всех живых
  (`MEME_ALL_REACTORS`);
- **12 часов** (`DEAD_POST_HOURS`) решают судьбу поста: отклики были → счётчик
  «Успешного успеха», не было → «Forever alone» + счётчик «Опиума»;
- «Forever alone» дополнительно требует, чтобы в чате ВООБЩЕ молчали: мем,
  проигнорированный посреди живого флуда, — это не «forever alone» (то же
  определение «живости», что у `services/dead_chat.py`).

Почему разбор — job, а не «событие → ачивка»: итог поста известен только ПОСЛЕ
окна. Прогон раз в 10 минут ограничивает задержку выдачи, стоит одну выборку
неразрешённых постов и идемпотентен (выдача ачивок — по unique-ключу).

Рубильник: `record_post` и разбор проверяют `game.enabled`. `record_response` и
`record_reaction` — НЕТ, и это осознанно: они лишь дописывают факты в УЖЕ
существующий пост, не производя ни опыта, ни ачивок, ни сообщений в чат. Лишняя
проверка флага стоила бы второго SELECT на самом горячем пути (каждое сообщение
в чате), а выключенная игра всё равно ничего не начислит — начисление гейтится
в фасаде.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_sessionmaker
from app.db.models import ChatMessage, GameMediaPost, User
from app.services.game import awards
from app.services.game.config import (
    DEAD_POST_HOURS,
    MEME_ALL_REACTORS,
    MEME_REACTION_WINDOW_MIN,
)
from app.services.game.flags import is_game_enabled

log = structlog.get_logger()

OUTCOME_ALIVE = "alive"
OUTCOME_DEAD = "dead"

# «Сразу под постом» — то же окно, что у реакции: задание даёт на отклик час.
RESPONSE_WINDOW = timedelta(minutes=MEME_REACTION_WINDOW_MIN)
DEAD_AFTER = timedelta(hours=DEAD_POST_HOURS)


def _ids(raw: list[int] | None) -> set[int]:
    """JSONB-список → set[int]. Чистая (тестируется без БД)."""
    return {int(uid) for uid in (raw or [])}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(moment: datetime) -> datetime:
    """Приводим к aware-UTC: из ТГ приходят aware-даты, но защищаемся от naive."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


async def _user_id(session: AsyncSession, telegram_id: int) -> int | None:
    """PK участника по TG-id. Чужаки телеметрию не двигают."""
    found = await session.scalar(select(User.id).where(User.telegram_id == telegram_id))
    return int(found) if found is not None else None


async def record_post(
    session: AsyncSession,
    *,
    chat_id: int,
    tg_message_id: int,
    telegram_id: int,
    kind: str,
    at: datetime | None = None,
    media_type: str | None = None,
    media_count: int | None = None,
    preview_file_id: str | None = None,
) -> bool:
    """Запомнить медиа-пост. False — уже записан / автор не участник / игра off.

    Дедупликация по (chat_id, tg_message_id): телеграм умеет доставить апдейт
    повторно, а двойной учёт сломал бы счётчики «Успешного успеха» и «Опиума».

    GHG11(10): вместе с постом пишем тип медиа, число файлов подборки и file_id
    миниатюры — из этого лента строит осмысленный анонс реакции бота.
    """
    if not await is_game_enabled(session):
        return False
    user_id = await _user_id(session, telegram_id)
    if user_id is None:
        return False
    existing = await session.scalar(
        select(GameMediaPost.id).where(
            GameMediaPost.chat_id == chat_id,
            GameMediaPost.tg_message_id == tg_message_id,
        )
    )
    if existing is not None:
        return False
    session.add(
        GameMediaPost(
            chat_id=chat_id,
            tg_message_id=tg_message_id,
            user_id=user_id,
            kind=kind,
            posted_at=_as_utc(at) if at else _now(),
            responders=[],
            window_responders=[],
            media_type=media_type,
            media_count=media_count,
            preview_file_id=preview_file_id,
        )
    )
    await session.commit()
    return True


async def record_bot_reaction(
    session: AsyncSession,
    *,
    chat_id: int,
    tg_message_id: int,
    emoji: str | None,
    phrase: str | None,
    at: datetime | None = None,
) -> tuple[int, int] | None:
    """GHG11(10): записать реакцию бота на пост. `(post_id, user_id)` или None.

    Заполненный `reacted_at` — признак, по которому лента (`feed.py`, вид
    `media`) показывает запись «бот отреагировал на …». Возвращаем id поста и
    автора, чтобы вызывающий код начислил опыт именно автору и не искал пост
    повторно.
    """
    post = await session.scalar(
        select(GameMediaPost).where(
            GameMediaPost.chat_id == chat_id,
            GameMediaPost.tg_message_id == tg_message_id,
        )
    )
    if post is None:
        return None
    post.reaction_emoji = emoji
    post.reaction_phrase = phrase
    post.reacted_at = _as_utc(at) if at else _now()
    await session.commit()
    return int(post.id), int(post.user_id)


async def _touch(
    session: AsyncSession,
    post: GameMediaPost,
    *,
    user_id: int,
    at: datetime,
    window_only: bool = False,
) -> bool:
    """Дописать отклик. False — он уже учтён (или автор сам себе «откликнулся»).

    Свои посты в отклики не засчитываем: «все живые отреагировали» не должно
    выполняться одним лишь фактом, что автор скинул второе сообщение.
    """
    if post.user_id == user_id or post.resolved_at is not None:
        return False
    moment = _as_utc(at)
    within = (moment - _as_utc(post.posted_at)) <= RESPONSE_WINDOW
    responders = _ids(post.responders)
    window = _ids(post.window_responders)
    changed = False
    if user_id not in responders:
        post.responders = [*sorted(responders), user_id]
        changed = True
    if within and user_id not in window:
        post.window_responders = [*sorted(window), user_id]
        changed = True
    if changed:
        await session.commit()
    return changed


async def record_reaction(
    session: AsyncSession,
    *,
    chat_id: int,
    tg_message_id: int,
    telegram_id: int,
    at: datetime | None = None,
) -> bool:
    """Живая реакция на пост. False — пост не наш/автор сам/уже учтён."""
    post = await session.scalar(
        select(GameMediaPost).where(
            GameMediaPost.chat_id == chat_id,
            GameMediaPost.tg_message_id == tg_message_id,
        )
    )
    if post is None:
        return False
    user_id = await _user_id(session, telegram_id)
    if user_id is None:
        return False
    return await _touch(session, post, user_id=user_id, at=at or _now())


async def record_message_response(
    session: AsyncSession,
    *,
    chat_id: int,
    telegram_id: int,
    at: datetime | None = None,
    reply_to_tg_message_id: int | None = None,
) -> bool:
    """Сообщение как отклик: reply на пост ИЛИ «ответ сразу под постом».

    Два случая задания в одной функции, потому что оба об одном: человек
    отреагировал СЛОВАМИ, а не эмодзи. Reply считаем в любое время (отвечают и
    через сутки), «ответ сразу под постом» — только внутри окна.
    """
    moment = _as_utc(at) if at else _now()
    user_id = await _user_id(session, telegram_id)
    if user_id is None:
        return False

    if reply_to_tg_message_id is not None:
        post = await session.scalar(
            select(GameMediaPost).where(
                GameMediaPost.chat_id == chat_id,
                GameMediaPost.tg_message_id == reply_to_tg_message_id,
                GameMediaPost.resolved_at.is_(None),
            )
        )
        if post is not None:
            # window_only=False: reply засчитываем как отклик, но «Мемолог» требует,
            # чтобы он был в окне (см. _touch: window_responders пополнится, если успел).
            return await _touch(session, post, user_id=user_id, at=moment)

    post = await session.scalar(
        select(GameMediaPost)
        .where(
            GameMediaPost.chat_id == chat_id,
            GameMediaPost.resolved_at.is_(None),
            GameMediaPost.posted_at <= moment,
            GameMediaPost.posted_at >= moment - RESPONSE_WINDOW,
        )
        .order_by(GameMediaPost.posted_at.desc())
        .limit(1)
    )
    if post is None:
        return False
    return await _touch(session, post, user_id=user_id, at=moment)


async def chat_was_silent(
    session: AsyncSession,
    *,
    chat_id: int,
    start: datetime,
    end: datetime,
    exclude_post_id: int,
) -> bool:
    """Молчал ли чат в интервале: ни текста, ни других медиа-постов.

    Считаем и медиа: цепочка мемов без текста — не «мёртвый чат» (то же решение
    принято в `media_reactions`/`dead_chat`), иначе «Forever alone» уехало бы
    тому, кто просто скинул одиночный мем в мемную серию.
    """
    text = await session.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .where(
            ChatMessage.chat_id == chat_id,
            ChatMessage.sent_at >= start,
            ChatMessage.sent_at <= end,
        )
    )
    if text:
        return False
    media = await session.scalar(
        select(func.count())
        .select_from(GameMediaPost)
        .where(
            GameMediaPost.chat_id == chat_id,
            GameMediaPost.id != exclude_post_id,
            GameMediaPost.posted_at >= start,
            GameMediaPost.posted_at <= end,
        )
    )
    return not media


def _memelog_eligible(post: GameMediaPost) -> bool:
    """«Все живые отреагировали» — по откликам, успевшим в окно. Чистая."""
    return len(_ids(post.window_responders)) >= MEME_ALL_REACTORS


async def resolve_due(
    session: AsyncSession, *, now: datetime | None = None
) -> dict[str, int]:
    """Разобрать неразрешённые посты. Возвращает счётчики для лога/тестов.

    Две фазы в одном проходе:
    1. окно закрылось → вынести вердикт по «Мемологу» (`memelog_done`);
    2. прошло 12 часов → выдать «Успешный успех» / «Forever alone»+«Опиум»
       и пометить пост разрешённым (повторно его не считаем никогда).
    """
    moment = _as_utc(now) if now else _now()
    stats = {"checked": 0, "memelog": 0, "alive": 0, "dead": 0, "silent": 0}
    posts = (
        await session.scalars(
            select(GameMediaPost).where(GameMediaPost.resolved_at.is_(None))
        )
    ).all()
    for post in posts:
        if post.resolved_at is not None:
            # Защита от двойного разбора: SQL уже фильтрует resolved, но если
            # выборку однажды перепишут, повторное начисление недопустимо.
            continue
        stats["checked"] += 1
        posted_at = _as_utc(post.posted_at)
        window_closed = moment - posted_at >= RESPONSE_WINDOW

        if window_closed and not post.memelog_done:
            if _memelog_eligible(post):
                await awards.meme_all_reacted(session, post.user_id)
                stats["memelog"] += 1
            # Вердикт выносим один раз: состав откликов в окне уже финальный.
            post.memelog_done = True
            await session.commit()

        if moment - posted_at < DEAD_AFTER:
            continue

        if _ids(post.responders):
            await awards.meme_reactions(session, post.user_id)
            post.outcome = OUTCOME_ALIVE
            stats["alive"] += 1
        else:
            silent = await chat_was_silent(
                session,
                chat_id=post.chat_id,
                start=posted_at,
                end=posted_at + DEAD_AFTER,
                exclude_post_id=post.id,
            )
            await awards.dead_post(session, post.user_id, silent_chat=silent)
            post.outcome = OUTCOME_DEAD
            stats["dead"] += 1
            if silent:
                stats["silent"] += 1
        post.resolved_at = moment
        await session.commit()

    return stats


async def run_memes_job() -> dict[str, int]:
    """Job планировщика: разобрать созревшие посты (регистрируется при игре on)."""
    sm = get_sessionmaker()
    async with sm() as session:
        if not await is_game_enabled(session):
            return {"checked": 0, "memelog": 0, "alive": 0, "dead": 0, "silent": 0}
        stats = await resolve_due(session)
    if stats["checked"]:
        log.info("game.memes_resolved", **stats)
    return stats
