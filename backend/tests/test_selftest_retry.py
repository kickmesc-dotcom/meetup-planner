"""GHG7 P0.4: двухступенчатая проверка selftest_send.

Жалоба: «80% случаев бот показан недоступным, хотя команды проходят».
Причина — флапающее соединение/прокси: одиночный getMe иногда моргает,
реальные команды на долгоживущих сессиях этого не замечают. Фикс:
при первом фейле getMe — пауза 1с и повтор. Никаких переключений
прокси/transport'а — путь отправки команд не трогаем.

Покрытые сценарии:
  1. Первая попытка ok → один вызов getMe, retried=False.
  2. Первая попытка timeout, вторая ok → retried=True, ok=True,
     first_error='timeout'.
  3. Обе попытки timeout → retried=True, ok=False, error='timeout',
     first_error='timeout'.
  4. Первая попытка — TelegramUnauthorizedError → НЕ ретраим (бот сам
     отвергнут, повтор не поможет). retried=False, ok=False, bot_active=True.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.services import proxies as proxies_mod
from app.services.proxies import selftest_send


class _FakeBot:
    """Мок aiogram-бота. `get_me` поведением управляется списком actions:
    каждый элемент — либо вызывает исключение, либо возвращает FakeUser.
    `actions` мутируется при каждом вызове (pop(0)).
    """

    def __init__(self, actions: list[Any]) -> None:
        self._actions = actions
        self.get_me_calls = 0
        # `session` — для проверки proxy_id_after_call. Без активного прокси.
        self.session = SimpleNamespace(_active_proxy_id=None)

    async def get_me(self):
        self.get_me_calls += 1
        if not self._actions:
            raise RuntimeError("no more actions configured")
        action = self._actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        # Иначе считаем что это success-возврат — FakeUser
        return action


class _FakeTelegramUnauthorizedError(Exception):
    """Подделка aiogram TelegramUnauthorizedError по имени класса.

    `_attempt_selftest` распознаёт «Telegram*»-исключения по
    __class__.__name__, поэтому реальный импорт aiogram не нужен.
    """


# Переопределяем имя класса так, чтобы matchить `exc.__class__.__name__ ==
# 'TelegramUnauthorizedError'` в _attempt_selftest.
_FakeTelegramUnauthorizedError.__name__ = "TelegramUnauthorizedError"


@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch):
    """В тестах паузу между попытками делаем нулевой, чтобы тесты были
    быстрыми. Реальное значение (1с) проверяется не здесь, а вручную в проде.
    """
    monkeypatch.setattr(proxies_mod, "_SELFTEST_RETRY_PAUSE_SEC", 0.0)


@pytest.mark.asyncio
async def test_first_try_ok_no_retry():
    bot = _FakeBot([SimpleNamespace(id=1, username="bot")])
    res = await selftest_send(bot, session=None)
    assert res.ok is True
    assert res.retried is False
    assert res.first_error is None
    assert res.error is None
    assert bot.get_me_calls == 1


@pytest.mark.asyncio
async def test_first_timeout_second_ok_marks_retried():
    bot = _FakeBot(
        [
            asyncio.TimeoutError(),
            SimpleNamespace(id=1, username="bot"),
        ]
    )
    res = await selftest_send(bot, session=None)
    assert res.ok is True
    assert res.retried is True
    assert res.first_error == "timeout"
    # Финальная ошибка пустая — успех.
    assert res.error is None
    assert bot.get_me_calls == 2
    assert res.bot_active is True


@pytest.mark.asyncio
async def test_both_timeouts_returns_failure_with_history():
    bot = _FakeBot(
        [
            asyncio.TimeoutError(),
            asyncio.TimeoutError(),
        ]
    )
    res = await selftest_send(bot, session=None)
    assert res.ok is False
    assert res.retried is True
    assert res.first_error == "timeout"
    assert res.error == "timeout"
    assert bot.get_me_calls == 2
    assert res.bot_active is False


@pytest.mark.asyncio
async def test_telegram_unauthorized_first_skips_retry():
    """Если первая попытка вернула TelegramUnauthorizedError — бот сам
    отвергнут, ретрай не поможет. НЕ делаем вторую попытку (экономим
    время и не тратим API-вызов на заведомо безнадёжный повтор).
    """
    bot = _FakeBot(
        [
            _FakeTelegramUnauthorizedError("invalid token"),
            # вторая в actions есть, но не должна быть использована
            SimpleNamespace(id=1, username="bot"),
        ]
    )
    res = await selftest_send(bot, session=None)
    assert res.ok is False
    assert res.retried is False
    assert res.first_error is None  # не было «первой и второй»
    assert res.bot_active is True   # Telegram-ошибка → бот жив
    assert bot.get_me_calls == 1    # вторая попытка НЕ была сделана
    assert res.error is not None and res.error.startswith("TelegramUnauthorizedError")
