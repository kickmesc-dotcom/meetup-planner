"""Чухан недели: каждый понедельник 12:00 МСК выбирается случайный участник
шестёрки с весами из конфига и публикуется в групповой чат.

Идемпотентно по `week_start` (UTC, понедельник 00:00) — повторный запуск
в ту же неделю не создаёт второй пост."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, time, timedelta, timezone

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import URLInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import User, WeeklyChukhan
from app.services.admin_config import get_chukhan_weights
from app.services.avatars import sync_user_avatar

log = structlog.get_logger()


def current_week_start(now: datetime | None = None) -> datetime:
    """Понедельник 00:00 UTC на неделю, в которую попадает `now`."""
    n = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    monday = (n - timedelta(days=n.weekday())).date()
    return datetime.combine(monday, time.min, tzinfo=timezone.utc)


def _pick_weighted(users: list[User], weight_map: dict[int, float]) -> User:
    weights = [max(0.0, weight_map.get(u.telegram_id, 1.0)) for u in users]
    if sum(weights) <= 0:
        weights = [1.0] * len(users)
    return random.choices(users, weights=weights, k=1)[0]


async def pick_chukhan_for_week(
    session: AsyncSession,
    *,
    week_start: datetime | None = None,
) -> tuple[WeeklyChukhan, User, bool]:
    """Возвращает (роу, пользователь, created): created=False если на эту неделю
    чухан уже был назначен.

    Внимание: при created=True вызывающий код обязан либо commit'нуть session
    после успешной публикации, либо rollback'нуть, если в TG ничего не ушло.
    Этот метод намеренно не коммитит — атомарность гарантирует announce_chukhan.
    """
    ws = week_start or current_week_start()
    existing = await session.scalar(
        select(WeeklyChukhan).where(WeeklyChukhan.week_start == ws)
    )
    if existing is not None:
        user = await session.get(User, existing.user_id)
        assert user is not None
        return existing, user, False

    users = list((await session.scalars(select(User))).all())
    if not users:
        raise RuntimeError("no users to pick from")

    weights = await get_chukhan_weights(session)
    chosen = _pick_weighted(users, weights)
    snapshot = {
        str(u.telegram_id): weights.get(u.telegram_id, 1.0) for u in users
    }
    row = WeeklyChukhan(
        week_start=ws,
        user_id=chosen.id,
        weights_snapshot=snapshot,
    )
    session.add(row)
    await session.flush()
    return row, chosen, True


CHUKHAN_TAGLINES = [
    "Поздравляем, носи гордо 🐓",
    "Неделя твоя, чухан. Не забудь занести.",
    "Готовь очко, чухан. Неделя будет длинная.",
    "Ты сегодня выиграл главный приз — звание чухана. Носи с гордостью, петух",
    "Чухан недели выявлен. Остальные могут выдохнуть.",
    "Веник, тапки и табуретка — твой новый трон.",
    "Будешь главным по шконке",
    "Чухан недели активирован. Остальным - принять ожидающую позу",
    "В мире чуханов, ты - премиум уровень.",
    "Выбор сделан, система не ошибается.",
    "Неделя твоя. Пользуйся моментом, пока остальные в тени.",
    "По версии жюри ты — самый сочный фрукт в этом огороде.",
    "Ты не искал этого звания, но оно нашло тебя. Классика.",
    "В чуханской иерархии ты сегодня поднялся на самый верх.",
    "Прими титул. Он тебе к лицу.",
    "Веник в углу, ведро у двери — звание подтверждено.",
    "Кто рано встал — тот и чухан. Расписание не врёт.",
    "Аватарка одобрена комиссией. Поздравляем 🤝",
]


def _format_announcement(user: User) -> str:
    name = user.display_name
    handle = f"@{user.username}" if user.username else name
    tagline = random.choice(CHUKHAN_TAGLINES)
    return (
        "💩💩💩 <b>ЧУХАН НЕДЕЛИ</b> 💩💩💩\n"
        "🤮🤢🤮🤢🤮🤢🤮🤢🤮\n\n"
        f"На этой неделе чуханом назначен:\n"
        f"👉 <b>{name}</b> ({handle}) 👈\n\n"
        "🪰💨🪰💨🪰💨🪰💨🪰\n"
        f"<i>{tagline}</i>"
    )


async def _drumroll(bot: Bot, chat_id: int, name: str) -> None:
    """Серия edit'ов одного сообщения для эффекта барабанной дроби.

    Шаги: 💩 → 💩💩💩 → 🥁🥁🥁 → имя. Между шагами 0.6с (Telegram rate-limit
    edit_message ≈ 1/с на чат, держим запас)."""
    frames = [
        "💩  …  💩",
        "💩💩  …  💩💩",
        "🥁🥁🥁 <b>чухан недели…</b> 🥁🥁🥁",
        f"🎉 <b>{name}</b> 🎉",
    ]
    msg = await bot.send_message(chat_id=chat_id, text=frames[0])
    for frame in frames[1:]:
        await asyncio.sleep(0.6)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg.message_id, text=frame
            )
        except TelegramAPIError as exc:
            log.warning("chukhan.drumroll_frame_failed", error=str(exc))
            break


async def announce_chukhan(bot: Bot, session: AsyncSession) -> WeeklyChukhan | None:
    settings = get_settings()
    if not settings.group_chat_id:
        log.info("chukhan.skip_no_group_chat")
        return None

    row, user, created = await pick_chukhan_for_week(session)
    if not created and row.posted_at is not None:
        log.info("chukhan.already_posted", week_start=row.week_start.isoformat())
        return row

    # Подтянуть актуальную аватарку перед публикацией.
    try:
        await sync_user_avatar(session, bot, user)
    except Exception:  # noqa: BLE001
        log.warning("chukhan.avatar_sync_failed", user_id=user.id)

    text = _format_announcement(user)
    # «Барабанная дробь» — best-effort, не блокирует основной пост.
    try:
        await _drumroll(bot, settings.group_chat_id, user.display_name)
    except TelegramAPIError as exc:
        log.warning("chukhan.drumroll_failed", error=str(exc))

    # Основной пост. Если TG не примет ни фото, ни текст — откатываем row.
    msg = None
    try:
        if user.avatar_url:
            try:
                msg = await bot.send_photo(
                    chat_id=settings.group_chat_id,
                    photo=URLInputFile(user.avatar_url),
                    caption=text,
                    disable_notification=False,
                )
            except TelegramAPIError as exc:
                log.warning("chukhan.send_photo_failed", error=str(exc))
        if msg is None:
            msg = await bot.send_message(
                chat_id=settings.group_chat_id,
                text=text,
                disable_notification=False,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("chukhan.send_failed_rollback", error=str(exc))
        if created:
            await session.rollback()
        return None

    row.posted_at = datetime.now(timezone.utc)
    row.tg_message_id = msg.message_id
    await session.commit()
    log.info(
        "chukhan.posted",
        week_start=row.week_start.isoformat(),
        user=user.display_name,
    )

    # Опрос-обжалование — best-effort, не критично для атомарности.
    try:
        await bot.send_poll(
            chat_id=settings.group_chat_id,
            question=f"Согласны с тем, что {user.display_name} — чухан недели?",
            options=["✅ Согласны", "🙅 Обжаловать"],
            is_anonymous=False,
            allows_multiple_answers=False,
            open_period=3600,
            reply_to_message_id=msg.message_id,
        )
    except TelegramAPIError as exc:
        log.warning("chukhan.appeal_poll_failed", error=str(exc))
    return row


async def run_chukhan_job(bot: Bot) -> None:
    """Точка входа для APScheduler — открывает свою сессию."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            await announce_chukhan(bot, session)
        except Exception:  # noqa: BLE001
            log.exception("chukhan.job_failed")
