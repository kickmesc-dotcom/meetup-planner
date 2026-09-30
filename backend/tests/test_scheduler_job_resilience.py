"""H2 (30.09): транзиентный сбой БД не должен ронять фоновый прогон целиком.

Прод-инцидент: `run_memes_job` упал на `socket.gaierror: Temporary failure in
name resolution` (контейнер Amvera на секунду не разрешил DNS до Neon), и это
убило весь прогон. `_logged_job` теперь распознаёт транзиентные сбои
подключения и повторяет прогон с экспоненциальной паузой, а нетранзиентные
ошибки (bad SQL, constraint) по-прежнему пробрасывает сразу.

Тесты держат три инварианта:
1. классификация `_is_transient_db_error` — DNS/сокет/таймаут/обрыв соединения
   транзиентны (в т.ч. завёрнутые SQLAlchemy в причину), логическая ошибка БД —
   нет;
2. обёртка реально повторяет и в итоге доходит до успеха;
3. обёртка не ретраит нетранзиентную ошибку и сдаётся после исчерпания попыток.
"""
from __future__ import annotations

import socket
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import app.bot.scheduler as scheduler
from app.bot.scheduler import _is_transient_db_error, _logged_job


class OperationalError(Exception):
    """Имитация sqlalchemy.exc.OperationalError (важно только имя класса)."""


class ConnectionDoesNotExistError(Exception):
    """Имитация asyncpg.exceptions.ConnectionDoesNotExistError."""


class UndefinedColumnError(Exception):
    """Имитация asyncpg.exceptions.UndefinedColumnError (логическая, не сеть)."""


@pytest.mark.parametrize(
    "exc",
    [
        socket.gaierror(-3, "Temporary failure in name resolution"),
        TimeoutError("database is not responding"),
        ConnectionResetError(104, "Connection reset by peer"),
        OperationalError("server closed the connection unexpectedly"),
        ConnectionDoesNotExistError("connection was closed in the middle"),
    ],
)
def test_transient_errors_are_classified(exc: BaseException) -> None:
    assert _is_transient_db_error(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("nope"),
        KeyError("missing"),
        UndefinedColumnError("column does not exist"),
    ],
)
def test_non_transient_errors_are_not_classified(exc: BaseException) -> None:
    assert _is_transient_db_error(exc) is False


def test_transient_error_found_in_cause_chain() -> None:
    """SQLAlchemy заворачивает сетевую ошибку в причину — её надо увидеть."""
    wrapper = RuntimeError("(builtins) wrapped")
    wrapper.__cause__ = socket.gaierror(-3, "Temporary failure")
    assert _is_transient_db_error(wrapper) is True


def test_cause_chain_cycle_terminates() -> None:
    """`__cause__`/`__context__` могут зациклиться — не вешаемся."""
    a = ValueError("a")
    b = ValueError("b")
    a.__cause__ = b
    b.__context__ = a
    assert _is_transient_db_error(a) is False


@pytest.mark.asyncio
async def test_job_retries_transient_failure_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(scheduler, "_SCHEDULER_DB_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(scheduler, "_SCHEDULER_DB_RETRY_BASE_DELAY_SEC", 0.0)
    calls = {"n": 0}

    async def flaky() -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise socket.gaierror(-3, "Temporary failure in name resolution")

    with patch("app.bot.scheduler.asyncio.sleep", new=AsyncMock()) as sleep:
        await _logged_job("test_flaky", flaky)()

    assert calls["n"] == 3  # 2 падения + успех
    assert sleep.await_count == 2  # пауза только между попытками


@pytest.mark.asyncio
async def test_job_gives_up_after_attempts_on_transient_failure(monkeypatch) -> None:
    monkeypatch.setattr(scheduler, "_SCHEDULER_DB_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(scheduler, "_SCHEDULER_DB_RETRY_BASE_DELAY_SEC", 0.0)
    calls = {"n": 0}

    async def always_down() -> None:
        calls["n"] += 1
        raise socket.gaierror(-3, "Temporary failure in name resolution")

    with patch("app.bot.scheduler.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(socket.gaierror):
            await _logged_job("test_down", always_down)()

    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_job_does_not_retry_non_transient_failure(monkeypatch) -> None:
    monkeypatch.setattr(scheduler, "_SCHEDULER_DB_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(scheduler, "_SCHEDULER_DB_RETRY_BASE_DELAY_SEC", 0.0)
    calls = {"n": 0}

    async def broken_sql() -> None:
        calls["n"] += 1
        raise UndefinedColumnError("column does not exist")

    with patch("app.bot.scheduler.asyncio.sleep", new=AsyncMock()) as sleep:
        with pytest.raises(UndefinedColumnError):
            await _logged_job("test_broken", broken_sql)()

    assert calls["n"] == 1  # логическую ошибку ретраить бессмысленно
    assert sleep.await_count == 0


@pytest.mark.asyncio
async def test_job_passes_through_kwargs_and_args() -> None:
    seen: dict[str, Any] = {}

    async def takes_bot(*, bot: Any) -> None:
        seen["bot"] = bot

    await _logged_job("test_kwargs", takes_bot)(bot="BOT")
    assert seen["bot"] == "BOT"
