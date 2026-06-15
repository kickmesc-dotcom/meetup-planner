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
        # Строим file-URL через сконфигурированный API-сервер бота, а НЕ хардкодом
        # на api.telegram.org. Прямой api.telegram.org из HF Space — мёртвый egress
        # (РКН-блокировка, инцидент 11–12.06): когда чухан-анонс делал
        # send_photo(URLInputFile(avatar_url)), aiogram качал байты по этому direct-
        # URL → timeout → пост молча падал в текстовый фолбэк (пропадало фото,
        # прод-фидбек 15.06 + п.4 «аватарки перестали обновляться»). `session.api`
        # уважает BOT_API_SERVER → cloudflare-воркер, который проксирует и Bot API,
        # и /file/-скачивание (проверено: HTTP 200, байт-в-байт). Один и тот же URL
        # рабочий и для бота из HF, и для <img> в мини-аппе на телефоне.
        url = bot.session.api.file_url(bot.token, file.file_path)
        if user.avatar_url != url:
            user.avatar_url = url
            await session.commit()
            log.info("avatar.synced", telegram_id=user.telegram_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("avatar.sync_failed", telegram_id=user.telegram_id, error=str(exc))


async def sync_all_avatars(session: AsyncSession, bot: Bot) -> int:
    """Возвращает количество пользователей, для которых выполнен запрос
    (не только тех, у кого аватар реально поменялся). Удобно для UI: показать
    «затронуто N пользователей». Ошибки на отдельных пользователях не прерывают
    остальных и логируются в `sync_user_avatar`."""
    users = list((await session.scalars(select(User))).all())
    for u in users:
        await sync_user_avatar(session, bot, u)
    return len(users)
