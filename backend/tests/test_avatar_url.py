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
async def test_commit_refreshes_synced_at_even_when_url_unchanged() -> None:
    # GHG8 (18.06 #2): семантика изменилась. Раньше «URL не поменялся → не
    # коммитим». Теперь `sync_user_avatar` пишет `avatar_synced_at` при КАЖДОМ
    # успешном синке (метка «когда последний раз тянули из TG» нужна меню
    # аватарок), поэтому commit ожидается даже при неизменном URL. Синк зовётся
    # редко (чухан раз/нед + ручной), лишней нагрузки на Neon не создаёт.
    worker = "https://telegram-proxy.kickmesc.workers.dev"
    bot = _FakeBot(worker)
    session = _FakeSession()
    user = _make_user()
    user.avatar_url = f"{worker}/file/botTESTTOKEN/photos/file_1.jpg"
    user.avatar_file_id = "FID_BIG"  # совпадает с _FakeBot → URL и id не меняются

    await sync_user_avatar(session, bot, user)

    session.commit.assert_awaited_once()
    assert user.avatar_synced_at is not None


@pytest.mark.asyncio
async def test_sync_writes_stable_file_id() -> None:
    # Ядро фикса 18.06 #2: синк сохраняет СТАБИЛЬНЫЙ file_id (не протухает),
    # из которого прокси-роут резолвит свежий file_path. До фикса хранился только
    # протухающий URL → «приложуха забывает аватарки».
    bot = _FakeBot("https://telegram-proxy.kickmesc.workers.dev")
    session = _FakeSession()
    user = _make_user()

    await sync_user_avatar(session, bot, user)

    assert user.avatar_file_id == "FID_BIG"
    assert user.avatar_synced_at is not None
    session.commit.assert_awaited_once()


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


# --- GHG8 (18.06 #2): URL для ОТОБРАЖЕНИЯ в мини-аппе (_avatar_display_url) ---
# Приоритет ручная → стабильный прокси → None; прямой протухающий avatar_url
# наружу мини-аппа НЕ отдаётся (в этом и был баг «забывает аватарки»).


def _patch_base_url(monkeypatch: Any, base: str) -> None:
    import app.api.routes_users as ru

    monkeypatch.setattr(
        ru, "get_settings", lambda: type("S", (), {"public_base_url": base})()
    )


def test_display_url_prefers_manual(monkeypatch: Any) -> None:
    from app.api.routes_users import _avatar_display_url

    _patch_base_url(monkeypatch, "https://app.example.com")
    u = _make_user()
    u.avatar_manual_url = "https://i.imgur.com/funny.jpg"
    u.avatar_file_id = "FID_BIG"  # есть и file_id — ручная всё равно приоритетнее
    u.avatar_url = "https://telegram-proxy.kickmesc.workers.dev/file/botX/p.jpg"

    assert _avatar_display_url(u) == "https://i.imgur.com/funny.jpg"


def test_display_url_uses_proxy_with_cache_bust(monkeypatch: Any) -> None:
    # Нет ручной, есть file_id → стабильный прокси-URL /api/avatar/{id}?v=…,
    # где ?v= завязан на file_id (меняется только при реальной смене аватара).
    from app.api.routes_users import _avatar_display_url

    _patch_base_url(monkeypatch, "https://app.example.com/")  # лишний слеш обрежется
    u = _make_user()
    u.avatar_file_id = "ABCDEFGHIJKLMNOP"  # последние 12 символов → ?v=
    u.avatar_url = "https://telegram-proxy.kickmesc.workers.dev/file/botX/p.jpg"

    url = _avatar_display_url(u)
    assert url == "https://app.example.com/api/avatar/7?v=EFGHIJKLMNOP"
    # Протухающий direct/file-URL в мини-апп НЕ просачивается.
    assert "/file/bot" not in url


def test_display_url_none_when_no_avatar(monkeypatch: Any) -> None:
    # Ни ручной, ни file_id → None (фронт рисует инициалы). Голый avatar_url
    # не используется (он протухает — корень бага 18.06 #2).
    from app.api.routes_users import _avatar_display_url

    _patch_base_url(monkeypatch, "https://app.example.com")
    u = _make_user()
    u.avatar_url = "https://telegram-proxy.kickmesc.workers.dev/file/botX/p.jpg"

    assert _avatar_display_url(u) is None


# --- GHG8 (18.06 #2): in-memory кеш file_path по стабильному file_id ---


def test_path_cache_roundtrip_and_ttl() -> None:
    from app.services import avatars

    avatars._avatar_path_cache.clear()
    avatars._cache_put_path("FID", "photos/x.jpg", now=1000.0)

    # В пределах TTL — попадание.
    assert avatars._cache_get_path("FID", now=1000.0 + 10) == "photos/x.jpg"
    # На границе/после TTL — промах, запись вычищена.
    expired_at = 1000.0 + avatars._AVATAR_PATH_TTL_SEC
    assert avatars._cache_get_path("FID", now=expired_at) is None
    assert "FID" not in avatars._avatar_path_cache


def test_path_cache_miss_for_unknown_id() -> None:
    from app.services import avatars

    avatars._avatar_path_cache.clear()
    assert avatars._cache_get_path("NOPE", now=1.0) is None


# --- GHG8 (18.06 #2): fetch_avatar_bytes — скачивание байт для прокси-роута ---


class _BufFake:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


@pytest.mark.asyncio
async def test_fetch_bytes_resolves_and_caches_path() -> None:
    from app.services import avatars
    from app.services.avatars import fetch_avatar_bytes

    avatars._avatar_path_cache.clear()
    bot = type("B", (), {})()
    bot.get_file = AsyncMock(return_value=type("F", (), {"file_path": "photos/a.png"})())
    bot.download_file = AsyncMock(return_value=_BufFake(b"PNGDATA"))

    data, ct = await fetch_avatar_bytes(bot, "FID")
    assert data == b"PNGDATA"
    assert ct == "image/png"  # по расширению .png
    bot.get_file.assert_awaited_once()

    # Второй вызов — file_path уже в кеше → get_file НЕ зовётся повторно.
    data2, _ = await fetch_avatar_bytes(bot, "FID")
    assert data2 == b"PNGDATA"
    bot.get_file.assert_awaited_once()  # всё ещё один раз


@pytest.mark.asyncio
async def test_fetch_bytes_evicts_cache_on_download_error() -> None:
    # Протух file_path между кешем и скачиванием → запись вычищается, None.
    from app.services import avatars
    from app.services.avatars import fetch_avatar_bytes

    avatars._avatar_path_cache.clear()
    avatars._cache_put_path("FID", "photos/stale.jpg", now=__import__("time").monotonic())
    bot = type("B", (), {})()
    bot.get_file = AsyncMock()
    bot.download_file = AsyncMock(side_effect=RuntimeError("404 expired"))

    result = await fetch_avatar_bytes(bot, "FID")
    assert result is None
    assert "FID" not in avatars._avatar_path_cache  # сброшено для перерезолва
