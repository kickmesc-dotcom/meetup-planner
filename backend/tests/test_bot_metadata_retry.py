"""SemiTaskBot: регистрация команд бота не должна «замолкать».

Реальный баг, поймавшийся на проде: `_register_bot_metadata` проглатывал своё
исключение, а цикл повторов выходил, как только встал вебхук. В итоге в меню
Telegram оставался старый список команд (`/report` и `/escalations` не
появлялись), хотя код их уже знал.

Проверяем именно это: пока команды не встали — попытки продолжаются.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("GROUP_CHAT_ID", "0")

import pytest  # noqa: E402

from app import main as app_main  # noqa: E402


@pytest.mark.asyncio
async def test_commands_are_retried_when_metadata_fails(monkeypatch):
    calls = {"webhook": 0, "metadata": 0}

    async def fake_webhook() -> None:
        calls["webhook"] += 1

    async def fake_metadata() -> bool:
        calls["metadata"] += 1
        # Первая попытка «не получилась», вторая — успешна.
        return calls["metadata"] >= 2

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(app_main, "_set_webhook", fake_webhook)
    monkeypatch.setattr(app_main, "_register_bot_metadata", fake_metadata)
    monkeypatch.setattr(app_main.asyncio, "sleep", fake_sleep)

    await app_main._register_telegram_metadata_with_retry()

    assert calls["webhook"] == 2
    assert calls["metadata"] == 2


@pytest.mark.asyncio
async def test_stops_after_first_success(monkeypatch):
    calls = {"webhook": 0, "metadata": 0}

    async def fake_webhook() -> None:
        calls["webhook"] += 1

    async def fake_metadata() -> bool:
        calls["metadata"] += 1
        return True

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(app_main, "_set_webhook", fake_webhook)
    monkeypatch.setattr(app_main, "_register_bot_metadata", fake_metadata)
    monkeypatch.setattr(app_main.asyncio, "sleep", fake_sleep)

    await app_main._register_telegram_metadata_with_retry()

    assert calls == {"webhook": 1, "metadata": 1}


@pytest.mark.asyncio
async def test_missing_group_does_not_block_menu_button(monkeypatch):
    """Отказ для одного scope не отменяет остальные шаги (баг 31.10.2026).

    На проде `set_my_commands(scope=Chat(GROUP_CHAT_ID))` отвечал
    `Bad Request: chat not found`: группу удалили или бот из неё вышел. Вызов
    стоял в общем `try`, поэтому вместе с ним отменялась и кнопка меню, а бот
    оставался со старым меню. Проверяем, что теперь кнопка ставится.
    """

    from types import SimpleNamespace

    class StubBot:
        def __init__(self) -> None:
            self.scopes: list[str] = []
            self.menu_set = False

        async def set_my_commands(self, commands, scope=None, request_timeout=None):
            from aiogram.types import BotCommandScopeChat

            if isinstance(scope, BotCommandScopeChat):
                raise RuntimeError("Bad Request: chat not found")
            self.scopes.append(type(scope).__name__)

        async def set_chat_menu_button(self, menu_button=None, request_timeout=None):
            self.menu_set = True

    bot = StubBot()
    monkeypatch.setattr(app_main, "get_bot", lambda: bot)
    monkeypatch.setattr(
        app_main,
        "get_settings",
        lambda: SimpleNamespace(
            group_chat_id=-100123,
            mini_app_url="https://example.com",
            tg_webhook_secret="test-secret",
        ),
    )

    commands_ok = await app_main._register_bot_metadata()

    # Команды в личке и в остальных группах встали, кнопка — тоже.
    assert commands_ok is True
    assert bot.scopes == ["BotCommandScopeAllPrivateChats", "BotCommandScopeAllGroupChats"]
    assert bot.menu_set is True
