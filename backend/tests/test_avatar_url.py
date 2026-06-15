"""GHG8 F-avatar-fix: URL аватарки строится через сконфигурированный API-сервер
бота (BOT_API_SERVER), а не хардкодом на api.telegram.org.

Регрессия (прод-фидбек 15.06 + п.4): прямой api.telegram.org из HF Space —
мёртвый egress (РКН, инцидент 11–12.06). Чухан-анонс делал
send_photo(URLInputFile(avatar_url)) → aiogram качал байты по direct-URL →
timeout → пост молча падал в текстовый фолбэк (пропадало фото). Фикс:
`sync_user_avatar` берёт URL из `bot.session.api.file_url`, который уважает
BOT_API_SERVER → cloudflare-воркер (он проксирует и Bot API, и /file/-скачивание).

БД-стенда в проекте нет (см. заголовок test_worm) — session.commit мокаем.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiogram.client.telegram import TelegramAPIServer

from app.db.models import User
from app.services.avatars import sync_user_avatar


class _FakeBotSession:
    """Имитация aiogram bot.session с заданным API-сервером (BOT_API_SERVER)."""

    def __init__(self, base: str) -> None:
        self.api = TelegramAPIServer.from_base(base)


class _FakeBot:
    """Минимальный bot: профильное фото есть, get_file отдаёт file_path."""

    def __init__(self, base: str, *, file_path: str | None = "photos/file_1.jpg") -> None:
        self.token = "TESTTOKEN"
        self.session = _FakeBotSession(base)
        self._file_path = file_path
        # photos.photos[0][-1].file_id — берём «самый крупный» размер.
        biggest = type("Sz", (), {"file_id": "FID_BIG"})()
        photos = type("Photos", (), {"photos": [[biggest]]})()
        self.get_user_profile_photos = AsyncMock(return_value=photos)
        file_obj = type("File", (), {"file_path": file_path})()
        self.get_file = AsyncMock(return_value=file_obj)


class _FakeSession:
    """Ловит commit; больше «sync_user_avatar» от session ничего не трогает."""

    def __init__(self) -> None:
        self.commit = AsyncMock()


def _make_user() -> User:
    u = User()
    u.id = 7
    u.telegram_id = 777
    u.display_name = "Кравченко"
    u.avatar_url = None
    return u


@pytest.mark.asyncio
async def test_avatar_url_uses_configured_api_server() -> None:
    # BOT_API_SERVER = cloudflare-воркер → URL должен указывать на воркер,
    # НЕ на api.telegram.org (мёртвый egress из HF).
    worker = "https://telegram-proxy.kickmesc.workers.dev"
    bot = _FakeBot(worker)
    session = _FakeSession()
    user = _make_user()

    await sync_user_avatar(session, bot, user)

    assert user.avatar_url == (
        f"{worker}/file/botTESTTOKEN/photos/file_1.jpg"
    )
    assert "api.telegram.org" not in user.avatar_url
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_avatar_url_default_base_when_no_proxy() -> None:
    # Без BOT_API_SERVER (direct) — поведение прежнее: api.telegram.org.
    bot = _FakeBot("https://api.telegram.org")
    session = _FakeSession()
    user = _make_user()

    await sync_user_avatar(session, bot, user)

    assert user.avatar_url == (
        "https://api.telegram.org/file/botTESTTOKEN/photos/file_1.jpg"
    )


@pytest.mark.asyncio
async def test_no_commit_when_url_unchanged() -> None:
    # Идемпотентность: если URL уже совпадает — не коммитим (экономим Neon).
    worker = "https://telegram-proxy.kickmesc.workers.dev"
    bot = _FakeBot(worker)
    session = _FakeSession()
    user = _make_user()
    user.avatar_url = f"{worker}/file/botTESTTOKEN/photos/file_1.jpg"

    await sync_user_avatar(session, bot, user)

    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_photo_is_noop() -> None:
    # Нет профильного фото → не трогаем avatar_url (кастомные аватарки целы).
    bot = _FakeBot("https://api.telegram.org")
    bot.get_user_profile_photos = AsyncMock(
        return_value=type("Photos", (), {"photos": []})()
    )
    session = _FakeSession()
    user = _make_user()
    user.avatar_url = "https://preview.redd.it/custom.jpg"

    await sync_user_avatar(session, bot, user)

    assert user.avatar_url == "https://preview.redd.it/custom.jpg"
    session.commit.assert_not_awaited()
