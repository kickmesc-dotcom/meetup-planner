from __future__ import annotations

from datetime import datetime, timezone

import structlog
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User

log = structlog.get_logger()

# In-memory кеш file_path по стабильному file_id. TG-овский file_path живёт ≥1ч;
# держим запись 50 мин, чтобы get_file к Telegram звался максимум раз в ~50 мин
# на участника (на free-tier важно не дёргать узкий канал к TG лишний раз).
# Прокси-роут /api/avatar/{id} читает этот кеш; промах → один get_file. Кеш
# module-level (как _state в proxies) — переживает запросы, гибнет с процессом.
_AVATAR_PATH_TTL_SEC = 50 * 60
_avatar_path_cache: dict[str, tuple[str, float]] = {}


def _cache_get_path(file_id: str, *, now: float) -> str | None:
    """Возвращает закешированный file_path для file_id, если не протух."""
    hit = _avatar_path_cache.get(file_id)
    if hit is None:
        return None
    path, expires_at = hit
    if now >= expires_at:
        _avatar_path_cache.pop(file_id, None)
        return None
    return path


def _cache_put_path(file_id: str, file_path: str, *, now: float) -> None:
    _avatar_path_cache[file_id] = (file_path, now + _AVATAR_PATH_TTL_SEC)


def _content_type_for(file_path: str) -> str:
    """TG фото — почти всегда JPEG; на всякий случай мапим по расширению."""
    lower = file_path.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


async def fetch_avatar_bytes(bot: Bot, file_id: str) -> tuple[bytes, str] | None:
    """Скачивает байты фото по СТАБИЛЬНОМУ file_id для прокси-роута мини-аппа.

    file_path резолвится из file_id и кешируется в памяти (≤ раз в 50 мин на id),
    байты тянутся через `bot.session` → уважает BOT_API_SERVER (cloudflare-воркер,
    прямой api.telegram.org из HF мёртв, инцидент 11–12.06). Возвращает
    (bytes, content_type) или None, если фото недоступно. Токен бота наружу не
    утекает: отдаём байты сами, а не редиректим на file-URL с токеном.
    """
    import time

    now = time.monotonic()
    file_path = _cache_get_path(file_id, now=now)
    try:
        if file_path is None:
            file = await bot.get_file(file_id)
            if not file.file_path:
                return None
            file_path = file.file_path
            _cache_put_path(file_id, file_path, now=now)
        buf = await bot.download_file(file_path)
        if buf is None:
            return None
        data = buf.read()
        return data, _content_type_for(file_path)
    except Exception as exc:  # noqa: BLE001
        # Протух file_path между кешем и скачиванием → сбросим, следующий запрос
        # перерезолвит. Не шумим в error — это штатная ситуация.
        _avatar_path_cache.pop(file_id, None)
        log.info("avatar.proxy_fetch_failed", file_id=file_id[:16], error=str(exc))
        return None


async def sync_user_avatar(session: AsyncSession, bot: Bot, user: User) -> None:
    """Запрашивает текущее фото профиля из Telegram и кеширует его.

    Пишет ДВА поля с разным сроком годности:
    - `avatar_file_id` — СТАБИЛЬНЫЙ id фото (не протухает). Источник правды для
      отображения в мини-аппе: прокси-роут /api/avatar/{id} резолвит по нему
      свежий file_path на лету (см. routes_users). Чинит «приложуха забывает
      аватарки» (прод-фидбек 18.06 #2) — раньше хранили только протухающий URL.
    - `avatar_url` — file-URL с file_path, живёт ≥1ч. ОСТАВЛЕН ради чухан-постинга
      (frozen-зона): он синкает аватар прямо перед send_photo, ссылка там всегда
      свежая. Для мини-аппа этот URL ненадёжен — там используем file_id.
    """
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
        # file_id — стабильный идентификатор фото; меняется только когда юзер
        # реально сменил аватар в TG. Это и есть «получил единожды — не забываем».
        changed = user.avatar_url != url or user.avatar_file_id != biggest.file_id
        user.avatar_url = url
        user.avatar_file_id = biggest.file_id
        user.avatar_synced_at = datetime.now(timezone.utc)
        await session.commit()
        if changed:
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
