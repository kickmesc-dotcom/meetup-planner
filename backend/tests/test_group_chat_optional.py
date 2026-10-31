"""Групповой чат — необязательная часть, а не условие работы.

Продукт перестроился: сотрудник заходит в мини-апп и выбирает команду сам.
Группа в Telegram полезна (анонсы, общий пул), но её отсутствие не должно
ломать ни старт, ни планировщик, ни API.

Реальный случай, ради которого это написано: `GROUP_CHAT_ID` указывал на чат,
откуда бота давно вывели (`400 Bad Request: chat not found`). Код при этом
продолжал считать чат настроенным и на каждом запуске бил в мёртвый id.

Проверяем три исхода проверки: жив, мёртв (выключаем), сеть подвела (оставляем).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402

from app.services import group_chat, org_bots  # noqa: E402


def _settings(chat_id: int | None) -> SimpleNamespace:
    """Настройки, которых хватает обоим модулям (полный Settings не нужен)."""
    return SimpleNamespace(
        group_chat_id_env=chat_id,
        bot_token="test-token",
        tg_webhook_secret="test-secret",
    )


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    group_chat.reset()
    org_bots.reset()
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(None))
    yield
    group_chat.reset()
    org_bots.reset()


class StubBot:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.calls: list[int] = []

    async def get_chat(self, chat_id, request_timeout=None):  # noqa: ANN001
        self.calls.append(chat_id)
        if self.error:
            raise RuntimeError(self.error)
        return {"id": chat_id}


@pytest.mark.asyncio
async def test_no_chat_configured_is_fine(monkeypatch):
    """Пустой `GROUP_CHAT_ID` — штатный режим: приложение работает без группы."""
    bot = StubBot()
    ok = await group_chat.validate_env_chat(bot)

    assert ok is False
    assert bot.calls == []  # даже не спрашиваем Telegram
    assert group_chat.state() == {"checked": True, "alive": False}
    assert org_bots.env_chat_disabled() is False


@pytest.mark.asyncio
async def test_missing_chat_is_disabled_once(monkeypatch):
    """`chat not found` → env-чат выключается, и `group_chat_id` становится None."""
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(-1003588632778))
    # Реестр как на старте: организация по умолчанию получила env-чат.
    await org_bots.reload(_EmptySession())

    bot = StubBot(error="Bad Request: chat not found")
    ok = await group_chat.validate_env_chat(bot)

    assert ok is False
    assert org_bots.env_chat_disabled() is True
    assert org_bots.chat_id_for(org_bots.DEFAULT_ORG_ID) is None
    # Повторная проверка бесплатна: второго сетевого вызова нет.
    await group_chat.validate_env_chat(bot)
    assert bot.calls == [-1003588632778]


@pytest.mark.asyncio
async def test_transient_failure_keeps_chat(monkeypatch):
    """Сеть подвела — чат не теряем: это не повод отключать рабочий id."""
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(-100))
    await org_bots.reload(_EmptySession())

    bot = StubBot(error="Request timeout")
    ok = await group_chat.validate_env_chat(bot)

    assert ok is True
    assert org_bots.env_chat_disabled() is False
    # Следующий старт попробует снова — результат не закэширован.
    assert group_chat.state()["checked"] is False


@pytest.mark.asyncio
async def test_live_chat_stays(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(-100))
    await org_bots.reload(_EmptySession())

    bot = StubBot()
    assert await group_chat.validate_env_chat(bot) is True
    assert org_bots.env_chat_disabled() is False
    assert group_chat.state() == {"checked": True, "alive": True}


class _EmptySession:
    """Пустой реестр организаций: для проверки отключения env-чата этого хватает.

    `org_bots.reload` сразу наполняет запись организации по умолчанию тем, что
    лежит в env, — ровно то состояние, в котором приложение стартует на хосте.
    """

    async def scalars(self, _query):  # noqa: ANN001
        return _EmptyScalars()


class _EmptyScalars:
    def __iter__(self):
        return iter(())

    def all(self):
        return []
