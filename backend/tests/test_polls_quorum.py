"""GHG6 G3 — авто-закрытие опроса по кворуму и пин announce-сообщения.

Покрытие:
1. `force_close_poll` — happy path: stop_poll успешен, `is_closed=True`, return True.
2. `force_close_poll` — уже закрытый полл: early return False, stop_poll не зовётся.
3. `force_close_poll` — `tg_message_id is None`: early return False.
4. `force_close_poll` — TG-ошибка: глотает, return False (но is_closed уже True).
5. `handle_game_choice_closed` пин announce-сообщения: pin_result=true → зовётся,
   false → не зовётся.

Стенд: AsyncMock на bot.stop_poll/bot.send_message + минимальный fake-Session
с тем-же интерфейсом, что нужен функциям (commit/scalar/refresh). Полноценный
sqlite-стенд для async-моделей в проект не тащим (другие сервисы тоже его
не имеют — см. test_worm, test_bot_pause, test_loser_cooldown_split).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from app.db.models import GameNomination, Poll, PollOption
from app.services.games_poll import handle_game_choice_closed
from app.services.polls import force_close_poll


class _FakeSession:
    """Минимальный async-session-stub.

    Нужен только `commit()` (для is_closed=True). Остальные методы — заглушки
    для случаев, когда вызовы не ожидаются.
    """

    def __init__(self) -> None:
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1

    async def scalar(self, _stmt: Any) -> Any:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None

    def add(self, _obj: Any) -> None:
        return None


def _make_poll(
    *,
    id_: int = 1,
    is_closed: bool = False,
    tg_message_id: int | None = 999,
    question: str = "Test [+pin][+when]",
) -> Any:
    """Фейковый Poll-объект.

    Не используем `Poll.__new__(Poll)` — SQLAlchemy InstrumentedAttribute
    требует валидной session-state, иначе `p.id = …` падает на
    `instance_state` (см. AttributeError при первом прогоне теста).
    Достаточно MagicMock без spec: тестируемый код обращается к атрибутам
    как обычным полям, и MagicMock без spec позволяет назначать любые
    атрибуты напрямую (но без `is_closed=…` через `spec=Poll`).
    """
    p = MagicMock()
    p.id = id_
    p.created_by = 1
    p.question = question
    p.closes_at = None
    p.created_at = datetime.now(timezone.utc)
    p.tg_message_id = tg_message_id
    p.tg_poll_id = "tg_poll_xyz"
    p.kind = "game_choice"
    p.game_nomination_id = None
    p.is_closed = is_closed
    return p


# --- force_close_poll ---


@pytest.mark.asyncio
async def test_force_close_happy_path():
    poll = _make_poll()
    sess = _FakeSession()
    bot = MagicMock()
    bot.stop_poll = AsyncMock(return_value=True)

    ok = await force_close_poll(sess, bot, poll, chat_id=100)

    assert ok is True
    assert poll.is_closed is True
    bot.stop_poll.assert_awaited_once_with(chat_id=100, message_id=999)
    assert sess.commit_calls == 1


@pytest.mark.asyncio
async def test_force_close_already_closed_is_noop():
    poll = _make_poll(is_closed=True)
    sess = _FakeSession()
    bot = MagicMock()
    bot.stop_poll = AsyncMock()

    ok = await force_close_poll(sess, bot, poll, chat_id=100)

    assert ok is False
    bot.stop_poll.assert_not_awaited()
    assert sess.commit_calls == 0


@pytest.mark.asyncio
async def test_force_close_no_message_id_is_noop():
    poll = _make_poll(tg_message_id=None)
    sess = _FakeSession()
    bot = MagicMock()
    bot.stop_poll = AsyncMock()

    ok = await force_close_poll(sess, bot, poll, chat_id=100)

    assert ok is False
    bot.stop_poll.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        TelegramForbiddenError(method=None, message="no rights"),
        TelegramAPIError(method=None, message="bad"),
        TelegramNetworkError(method=None, message="oops"),
        TelegramRetryAfter(method=None, message="flood", retry_after=30),
        asyncio.TimeoutError(),
    ],
)
async def test_force_close_swallows_tg_errors(exc: Exception):
    poll = _make_poll()
    sess = _FakeSession()
    bot = MagicMock()
    bot.stop_poll = AsyncMock(side_effect=exc)

    # is_closed выставляется ДО stop_poll и коммитится — это защита от двойного
    # срабатывания auto-close на следующем голосе. Поэтому даже при TG-ошибке
    # is_closed=True, и повторный record_poll_answer уже не вызовет stop_poll.
    ok = await force_close_poll(sess, bot, poll, chat_id=100)

    assert ok is False
    assert poll.is_closed is True
    assert sess.commit_calls == 1


# --- handle_game_choice_closed: pin_result поведение ---


@pytest.mark.asyncio
async def test_game_choice_closed_pins_when_pin_result_true():
    """pin_result=true + есть winner → pin_message_safely зовётся на announce."""
    poll = _make_poll(question="Во что сыграем? [+pin]")  # без [+when], чтобы
    # не уходить в follow-up create_game_when_poll и не тащить весь Stack
    winner_opt = MagicMock(spec=PollOption)
    winner_opt.label = "Dota 2"

    bot = MagicMock()
    sent_msg = MagicMock()
    sent_msg.message_id = 12345
    bot.send_message = AsyncMock(return_value=sent_msg)

    sess = _FakeSession()

    with (
        patch("app.services.games_poll.pick_winner_option", new=AsyncMock(return_value=winner_opt)),
        patch("app.services.admin_config.get_polls_pin_result", new=AsyncMock(return_value=True)),
        patch("app.bot.utils.pinning.pin_message_safely", new=AsyncMock(return_value=True)) as pin_mock,
    ):
        # nomination=None, чтобы follow-up не создавался даже если [+when] в q.
        with patch.object(sess, "scalar", new=AsyncMock(return_value=None)):
            await handle_game_choice_closed(sess, bot, poll=poll, chat_id=100)

    bot.send_message.assert_awaited_once()
    pin_mock.assert_awaited_once_with(bot, chat_id=100, message_id=12345)


@pytest.mark.asyncio
async def test_game_choice_closed_no_pin_when_pin_result_false():
    poll = _make_poll(question="Во что сыграем?")
    winner_opt = MagicMock(spec=PollOption)
    winner_opt.label = "Dota 2"

    bot = MagicMock()
    sent_msg = MagicMock()
    sent_msg.message_id = 12345
    bot.send_message = AsyncMock(return_value=sent_msg)

    sess = _FakeSession()

    with (
        patch("app.services.games_poll.pick_winner_option", new=AsyncMock(return_value=winner_opt)),
        patch("app.services.admin_config.get_polls_pin_result", new=AsyncMock(return_value=False)),
        patch("app.bot.utils.pinning.pin_message_safely", new=AsyncMock(return_value=True)) as pin_mock,
    ):
        with patch.object(sess, "scalar", new=AsyncMock(return_value=None)):
            await handle_game_choice_closed(sess, bot, poll=poll, chat_id=100)

    bot.send_message.assert_awaited_once()
    pin_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_game_choice_closed_no_pin_on_send_failure():
    """send_message упал → announce-сообщения нет, пинить нечего, даже
    при pin_result=true."""
    poll = _make_poll(question="Во что сыграем? [+pin]")
    winner_opt = MagicMock(spec=PollOption)
    winner_opt.label = "Dota 2"

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("boom"))

    sess = _FakeSession()

    with (
        patch("app.services.games_poll.pick_winner_option", new=AsyncMock(return_value=winner_opt)),
        patch("app.services.admin_config.get_polls_pin_result", new=AsyncMock(return_value=True)),
        patch("app.bot.utils.pinning.pin_message_safely", new=AsyncMock(return_value=True)) as pin_mock,
    ):
        with patch.object(sess, "scalar", new=AsyncMock(return_value=None)):
            await handle_game_choice_closed(sess, bot, poll=poll, chat_id=100)

    pin_mock.assert_not_awaited()
