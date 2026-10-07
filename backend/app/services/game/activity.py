"""Э18: единый режим «активностей» бота — живые часы и «не перебивать флуд».

Заказчик: «бот должен больше разбавлять тишину, нежели перебивать в моменты
обсуждений» и «пул живых часов хотя бы с 10 до 22». Эти два правила общие для
всех АВТО-постов бота (случайные события, голосовые задания, музыка, гиммики),
поэтому живут здесь, а не в каждом модуле отдельно.

Две проверки:

* **Живые часы.** Локальное время чата (UTC + смещение, МСК = +3) должно попадать
  в окно `[day_start_hour, day_end_hour)`. Ночью бот молчит.
* **Не перебивать.** Если в чате писали за последние `quiet_minutes` минут — бот
  НЕ влезает со своим постом: он разбавляет тишину, а не спор.

Источник «недавней активности» — `chat_messages` (тот же, что у мем-телеметрии).
Проверки дешёвые (один индексированный COUNT) и не пишут в БД.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    ChatMessage,
    GameJournalEntry,
    GamePrompt,
    GameVoiceTask,
    MusicGameRound,
    MusicSelection,
)
from app.services.game.config import ACTIVITY_TZ_OFFSET_HOURS

# Результаты проверки (строки — для логов/отладки, не для пользователя).
OK = "ok"
NIGHT = "night"
BUSY = "busy"
BUDGET = "budget"


def local_hour(now: datetime, *, offset_hours: int = ACTIVITY_TZ_OFFSET_HOURS) -> int:
    """Час в ЛОКАЛЬНОМ времени чата (UTC + смещение). Чистая функция."""
    return (now.astimezone(timezone.utc).hour + offset_hours) % 24


def local_day(now: datetime, *, tz_offset: int = ACTIVITY_TZ_OFFSET_HOURS) -> date:
    """Дата ЛОКАЛЬНЫХ суток чата (UTC + смещение). Чистая функция.

    Именно она, а не `now.date()`, определяет, что считать «сегодня»: сутки
    сбрасываются в 00:00 по времени чата, а не по UTC. Иначе ночью (21:00–24:00
    UTC = 00:00–03:00 МСК) «сегодня» в лимитах расходилось с живыми часами.
    """
    return (now.astimezone(timezone.utc) + timedelta(hours=tz_offset)).date()


def local_day_bounds(
    now: datetime, *, tz_offset: int = ACTIVITY_TZ_OFFSET_HOURS
) -> tuple[datetime, datetime]:
    """Границы ЛОКАЛЬНЫХ суток (UTC+смещение) как UTC-моменты. Чистая функция.

    Один источник правды для всего, что считает «за день»: бюджет авто-постов,
    суточные лимиты событий и суточные ачивки. Так сброс у них общий — 00:00 МСК.
    """
    moment = now.astimezone(timezone.utc)
    local = moment + timedelta(hours=tz_offset)
    start_local = datetime.combine(local.date(), time.min)
    start = (start_local - timedelta(hours=tz_offset)).replace(tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def is_daytime(
    now: datetime, *, start_hour: int, end_hour: int, offset_hours: int = ACTIVITY_TZ_OFFSET_HOURS
) -> bool:
    """Попадает ли момент в живые часы. Чистая функция.

    Верхняя граница исключающая (в 22:00 новое уже не уходит). `start == end` —
    окно «на весь день»; `start > end` — окно через полночь (22–06).
    """
    hour = local_hour(now, offset_hours=offset_hours)
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


# --------------------------------------------------------------------------
# GHG11(8): разбор ответов промпта на «кнопки» и «нужен ли текст»
#
# Нужен и API (`routes_game._activity_options`), и ленте (`feed.py`): анонс
# задания в ленте должен приносить с собой интерфейс участия. Держим правило
# в одном месте, чтобы кнопки в ленте и в блоке «Активности» не разошлись.
# --------------------------------------------------------------------------


def split_activity_options(
    answers: list[dict] | None,
) -> tuple[list[tuple[str, int]], bool]:
    """Ответы промпта → (кнопки[(подпись, xp)], нужен свободный ввод). Чистая.

    Кнопка — там, где у ответа есть человеческая `label`. Если хоть один ответ
    без подписи и не медиа — нужен свободный ввод. Если ни кнопок, ни текстового
    варианта не нашлось (например, только медиа) — всё равно даём ввод: ссылку
    на мем можно прислать текстом.
    """
    options: list[tuple[str, int]] = []
    needs_text = False
    for ans in answers or []:
        label = str(ans.get("label") or "").strip()
        if label:
            options.append((label, int(ans.get("xp") or 0)))
        elif not ans.get("media"):
            needs_text = True
    if not options and not needs_text:
        needs_text = True
    return options, needs_text


async def recent_message_count(
    session: AsyncSession, chat_id: int, *, minutes: int, now: datetime
) -> int:
    """Сколько сообщений в чате за последние `minutes` минут. Один COUNT."""
    if minutes <= 0:
        return 0
    since = now - timedelta(minutes=minutes)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.chat_id == chat_id, ChatMessage.sent_at >= since)
        )
        or 0
    )


async def count_auto_posts_today(
    session: AsyncSession, *, now: datetime, tz_offset: int = ACTIVITY_TZ_OFFSET_HOURS
) -> int:
    """Сколько АВТО-постов бот сделал за текущие ЛОКАЛЬНЫЕ сутки.

    Единый бюджет дня поверх всех фич, но БЕЗ отдельного леджера и миграции:
    считаем созданные сегодня строки существующих таблиц авто-постов
    (`game_prompts`, `game_voice_tasks`, `music_selections`, `music_game_rounds`)
    плюс число выплесков журнала — уникальные `sent_at` за день (одна сводка =
    одно сообщение, даже если в ней десять ачивок).
    """
    start, end = local_day_bounds(now, tz_offset=tz_offset)
    total = 0
    for model in (GamePrompt, GameVoiceTask, MusicSelection, MusicGameRound):
        total += int(
            await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.created_at >= start, model.created_at < end)
            )
            or 0
        )
    total += int(
        await session.scalar(
            select(func.count(func.distinct(GameJournalEntry.sent_at))).where(
                GameJournalEntry.sent_at >= start,
                GameJournalEntry.sent_at < end,
            )
        )
        or 0
    )
    return total


async def check_window(
    session: AsyncSession, *, now: datetime, chat_id: int | None = None
) -> str:
    """Можно ли постить сейчас: `OK` / `NIGHT` / `BUSY` / `BUDGET`.

    Ленивый импорт геттеров — чтобы модуль не тянул admin_config на импорте
    (и тесты могли подменять его точечно).
    """
    from app.services.admin_config import (
        get_activity_day_end_hour,
        get_activity_day_start_hour,
        get_activity_max_posts_per_day,
        get_activity_quiet_minutes,
    )

    if not is_daytime(
        now,
        start_hour=await get_activity_day_start_hour(session),
        end_hour=await get_activity_day_end_hour(session),
    ):
        return NIGHT

    quiet = await get_activity_quiet_minutes(session)
    if quiet > 0:
        target = chat_id or get_settings().group_chat_id
        if target and await recent_message_count(
            session, target, minutes=quiet, now=now
        ):
            return BUSY

    # Единый бюджет дня — последняя проверка: если исчерпан, не постит ни одна
    # фича (бюджет общий, а не на каждую механику отдельно).
    budget = await get_activity_max_posts_per_day(session)
    if budget > 0 and await count_auto_posts_today(session, now=now) >= budget:
        return BUDGET
    return OK
