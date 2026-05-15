from __future__ import annotations

import structlog
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User

log = structlog.get_logger()


async def sync_user_avatar(session: AsyncSession, bot: Bot, user: User) -> None:
    """Fetch the user's current Telegram profile photo and cache its file URL."""
    try:
        photos = await bot.get_user_profile_photos(user.telegram_id, limit=1)
        if not photos.photos:
            return
        # The largest size is the last entry in the inner list.
        biggest = photos.photos[0][-1]
        file = await bot.get_file(biggest.file_id)
        if not file.file_path:
            return
        url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
        if user.avatar_url != url:
            user.avatar_url = url
            await session.commit()
            log.info("avatar.synced", telegram_id=user.telegram_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("avatar.sync_failed", telegram_id=user.telegram_id, error=str(exc))


async def sync_all_avatars(session: AsyncSession, bot: Bot) -> None:
    users = list((await session.scalars(select(User))).all())
    for u in users:
        await sync_user_avatar(session, bot, u)
