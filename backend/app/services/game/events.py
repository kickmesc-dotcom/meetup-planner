"""GHG10 Э13: случайные события, которые требуют действия в чате.

Механика одной строкой: бот постит призыв, ждёт сообщение, подходящее под один
из ответов каталога, и первому подходящему выдаёт опыт. Идея заказчика — «это
заставляет людей взаимодействовать с ботом даже без команды».

Три предохранителя от спама, потому что событие пишет в чат само, без запроса:

* **Редко.** `game.events.min_gap_hours` между промптами и
  `game.events.max_per_day` в сутки.
* **Вероятностно.** `game.events.chance_percent` — «может выпасть, а может
  нет»: даже в разрешённом окне промпт выпадает не всегда.
* **Без повторов.** Промпт, который уже был, уходит в кулдаун
  (`Prompt.cooldown_days`), а не сыплется второй раз подряд.

Мастер-рубильник — общий игровой (`game.enabled`) плюс свой
(`game.events.enabled`); при выключенном игра вообще не регистрирует job.
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import GamePrompt, User
from app.services.admin_config import (
    get_game_events_chance_percent,
    get_game_events_enabled,
    get_game_events_max_per_day,
    get_game_events_min_gap_hours,
)
from app.services.game import awards, journal
from app.services.game.events_catalog import (
    PROMPTS,
    PROMPTS_BY_CODE,
    Prompt,
    serialize_answers,
)

log = structlog.get_logger()


# --------------------------------------------------------------------------
# Чистая часть: матчинг и текст
# --------------------------------------------------------------------------


def match_answer(
    answers: list[dict], *, text: str | None, has_media: bool
) -> dict | None:
    """Первый подходящий ответ или None. Чистая функция (тесты).

    Медиа-ответы засчитываются только по медиа, текстовые — только по тексту:
    иначе «скинь мем» отдавало бы +50 XP за первое же сообщение в чате.
    """
    for answer in answers:
        pattern = answer.get("matcher") or ""
        if answer.get("media"):
            if has_media:
                return answer
            continue
        if not text:
            continue
        try:
            if re.search(pattern, text.strip(), re.IGNORECASE):
                return answer
        except re.error:
            log.warning("game.event_bad_matcher", pattern=pattern)
            continue
    return None


def render_reply(template: str, *, name: str, xp: int) -> str:
    """Подставить имя и награду в текст ответа. Чистая функция."""
    try:
        return template.format(name=name, xp=xp)
    except (KeyError, IndexError, ValueError):
        return template


def pick_prompt(*, used_codes: set[str], rng: random.Random) -> Prompt | None:
    """Выбрать промпт вне кулдауна. Чистая функция (тесты)."""
    free = [p for p in PROMPTS if p.code not in used_codes]
    if not free:
        return None
    return rng.choice(free)


# --------------------------------------------------------------------------
# Планировщик
# --------------------------------------------------------------------------


async def close_expired(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Закрыть промпты, у которых вышло время. Победителя в них нет — молчим."""
    moment = now or datetime.now(timezone.utc)
    result = await session.execute(
        update(GamePrompt)
        .where(GamePrompt.closed_at.is_(None), GamePrompt.expires_at <= moment)
        .values(closed_at=moment, outcome="expired")
    )
    await session.commit()
    return int(result.rowcount or 0)


async def run_events_job(
    *, now: datetime | None = None, rng: random.Random | None = None
) -> int:
    """Тик планировщика: закрыть просроченные и, если повезло, выкатить новый промпт."""
    from app.db.base import get_sessionmaker

    moment = now or datetime.now(timezone.utc)
    dice = rng or random.Random()
    sm = get_sessionmaker()
    async with sm() as session:
        await close_expired(session, now=moment)
        if not await get_game_events_enabled(session):
            return 0

        settings = get_settings()
        chat_id = settings.group_chat_id
        if not chat_id:
            return 0

        # 1. Пауза между событиями.
        last_at = await session.scalar(select(func.max(GamePrompt.created_at)))
        gap_hours = await get_game_events_min_gap_hours(session)
        if last_at is not None:
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=timezone.utc)
            if moment - last_at < timedelta(hours=gap_hours):
                return 0

        # 2. Суточный потолок.
        day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        today = int(
            await session.scalar(
                select(func.count())
                .select_from(GamePrompt)
                .where(GamePrompt.created_at >= day_start)
            )
            or 0
        )
        if today >= await get_game_events_max_per_day(session):
            return 0

        # 3. Везение.
        if dice.randint(1, 100) > await get_game_events_chance_percent(session):
            return 0

        # 4. Что не повторяем.
        cooldowns: set[str] = set()
        for code in PROMPTS_BY_CODE:
            prompt = PROMPTS_BY_CODE[code]
            since = moment - timedelta(days=prompt.cooldown_days)
            recent = await session.scalar(
                select(func.count())
                .select_from(GamePrompt)
                .where(GamePrompt.code == code, GamePrompt.created_at >= since)
            )
            if recent:
                cooldowns.add(code)
        chosen = pick_prompt(used_codes=cooldowns, rng=dice)
        if chosen is None:
            return 0

        session.add(
            GamePrompt(
                chat_id=chat_id,
                code=chosen.code,
                text=chosen.text,
                answers=serialize_answers(chosen),
                expires_at=moment + timedelta(minutes=chosen.ttl_minutes),
            )
        )
        await session.commit()

        # Призыв ждёт ответа — значит идёт через журнал: в режиме сводки он
        # «выпадет» в чат ближайшим окном, а не посреди тишины.
        await journal.announce(session, kind=journal.KIND_EVENT, text=chosen.text)
    log.info("game.event_posted", code=chosen.code)
    return 1


# --------------------------------------------------------------------------
# Горячий путь: ответ в чате
# --------------------------------------------------------------------------


async def try_answer(
    session: AsyncSession,
    *,
    chat_id: int,
    telegram_id: int,
    text: str | None,
    has_media: bool = False,
    at: datetime | None = None,
) -> bool:
    """Сообщение может быть ответом на открытый промпт. True — кто-то выиграл.

    Вызывается из обработчика КАЖДОГО сообщения, поэтому начинается с одного
    индексного SELECT'а по (chat_id, closed_at, expires_at) — нет открытых
    промптов, нет и работы.
    """
    moment = at or datetime.now(timezone.utc)
    prompt = await session.scalar(
        select(GamePrompt)
        .where(
            GamePrompt.chat_id == chat_id,
            GamePrompt.closed_at.is_(None),
            GamePrompt.expires_at > moment,
        )
        .order_by(GamePrompt.id.asc())
        .limit(1)
    )
    if prompt is None:
        return False

    matched = match_answer(list(prompt.answers or []), text=text, has_media=has_media)
    if matched is None:
        return False

    # ⚠️ Через `execute(...).first()`, а НЕ `scalar(...)`: `scalar` возвращает
    # первую КОЛОНКУ первой строки, поэтому на двухколоночном select он отдаёт
    # `int`, и `user_row[0]` падает с «'int' object is not subscriptable».
    # С этой ошибкой соц-слой не засчитал ни одного ответа на событие в бою:
    # исключение улетало в `game_social_failed` до `prompt.closed_at = moment`.
    found = (
        await session.execute(
            select(User.id, User.display_name).where(User.telegram_id == telegram_id)
        )
    ).first()
    if found is None:
        return False
    user_id, name = int(found[0]), found[1]

    # Сначала закрываем промпт: он одноразовый, и даже сбой начисления не должен
    # дать второму участнику ту же награду.
    prompt.closed_at = moment
    prompt.outcome = "won"
    prompt.winner_user_id = user_id
    await session.commit()

    points = int(matched.get("xp") or 0)
    if points:
        await awards.event(session, user_id, points=points, prompt_id=prompt.id)
    await journal.announce(
        session,
        kind=journal.KIND_EVENT,
        subject_user_id=user_id,
        text="⚡️ " + render_reply(
            matched.get("reply") or "<b>{name}</b>: +{xp} XP.", name=name, xp=points
        ),
    )
    log.info("game.event_won", code=prompt.code, user_id=user_id, xp=points)
    return True
