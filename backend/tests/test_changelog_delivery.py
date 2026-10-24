"""`/changelog` не имеет права молчать.

Владелец дважды писал команду и не получал ничего — при том, что остальные
команды работали. Поэтому здесь проверяется не содержание истории, а
доставка: три уровня ответа и запасной путь без `reply` (чат мог запретить
ответы на сообщения).
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import types  # noqa: E402

import pytest  # noqa: E402
from aiogram.exceptions import TelegramBadRequest  # noqa: E402
from aiogram.methods import SendMessage  # noqa: E402

from app.bot.handlers import changelog as handler  # noqa: E402
from app.services import changelog as service  # noqa: E402


class FakeMessage:
    """Сообщение, которое помнит, каким способом его отправили."""

    def __init__(self, *, reply_ok: bool = True) -> None:
        self.reply_ok = reply_ok
        self.calls: list[tuple[str, dict]] = []
        # Логгер обработчика читает чат и id — без них падает до отправки.
        self.chat = types.SimpleNamespace(type="private")
        self.message_id = 1

    async def reply(self, text, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append(("reply", {"text": text, **kwargs}))
        if not self.reply_ok:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=1, text="x"),
                message="message can't be replied",
            )
        return True

    async def answer(self, text, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append(("answer", {"text": text, **kwargs}))
        return True


@pytest.fixture(autouse=True)
def _no_real_pause(monkeypatch):
    async def fake_pause(_seconds: float) -> None:
        return None

    monkeypatch.setattr(handler, "_pause", fake_pause)


async def test_deliver_can_send_without_reply(monkeypatch):
    """Запасной путь: обычная отправка, когда ответ на сообщение запрещён."""
    message = FakeMessage(reply_ok=False)

    assert await handler._deliver(message, "текст", as_reply=False) is True
    assert message.calls[-1][0] == "answer"


async def test_changelog_answers_even_when_history_fails(monkeypatch):
    """GitHub/сеть упали — человек всё равно получает короткий ответ."""

    async def boom() -> service.Changelog:
        raise RuntimeError("github is down")

    monkeypatch.setattr(handler, "build_changelog", boom)
    message = FakeMessage()

    await handler.on_changelog(message)

    assert message.calls, "обработчик промолчал — это и есть баг"
    sent = message.calls[0][1]["text"]
    assert "Что нового" in sent


async def test_changelog_uses_short_plain_answer_when_html_rejected(monkeypatch):
    """HTML не прошёл — уходит короткая версия без разметки."""

    async def view() -> service.Changelog:
        return service.build_view([], source_ok=False)

    class HtmlRejecting(FakeMessage):
        async def reply(self, text, **kwargs):  # noqa: ANN001, ANN003
            self.calls.append(("reply", {"text": text, **kwargs}))
            if kwargs.get("parse_mode") == "HTML":
                raise TelegramBadRequest(
                    method=SendMessage(chat_id=1, text="x"),
                    message="can't parse entities",
                )
            return True

    monkeypatch.setattr(handler, "build_changelog", view)
    message = HtmlRejecting()

    await handler.on_changelog(message)

    plain = [c for c in message.calls if c[1].get("parse_mode") is None]
    assert plain, "не попытались отправить версию без разметки"
