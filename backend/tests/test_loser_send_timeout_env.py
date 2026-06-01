"""GHG7 P8.1/P8.2/P8.6: env-таймаут отправки лоха (LOSER_SEND_TIMEOUT).

Прод-инцидент 30.05: автолох падал в TimeoutError, потому что send оборачивался
в `asyncio.wait_for(8s)`, а сессия бота держит соединение до 30с. «Случайная
фраза» шлёт без обёртки и доходит при throttling канала (РКН отвечает 8–30с) —
лох же резался на 8с. Фикс: таймаут читается из env LOSER_SEND_TIMEOUT (дефолт
25с), общий для автолоха (scheduler._env_int) и публичного /loser/roll
(routes_meetings._loser_send_timeout).

Покрытые сценарии для каждого парсера:
  1. env не задан → дефолт.
  2. env задан числом → распарсенное значение.
  3. env задан мусором → фолбэк на дефолт (без падения).
"""
from __future__ import annotations

import pytest

from app.api.routes_meetings import _loser_send_timeout
from app.bot.scheduler import _env_int


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, 25.0),       # не задан → дефолт
        ("25", 25.0),       # дефолтное значение явно
        ("40", 40.0),       # кастомное число
        ("0", 0.0),         # граничный 0 — валиден, парсится
        ("not-a-number", 25.0),  # мусор → фолбэк
        ("12.5", 25.0),     # float-строка не int → фолбэк (env у нас целочисленный)
        ("", 25.0),         # пустая строка → фолбэк
    ],
)
def test_loser_send_timeout_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("LOSER_SEND_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("LOSER_SEND_TIMEOUT", raw)
    result = _loser_send_timeout()
    assert result == expected
    assert isinstance(result, float)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, 25),         # не задан → дефолт
        ("25", 25),         # дефолт явно
        ("40", 40),         # кастомное число
        ("0", 0),           # граничный 0
        ("not-a-number", 25),    # мусор → фолбэк
        ("12.5", 25),       # float-строка не int → фолбэк
        ("", 25),           # пустая строка → фолбэк
    ],
)
def test_scheduler_env_int_loser_timeout(monkeypatch, raw, expected):
    """scheduler._env_int — общий целочисленный парсер env, на нём построен
    _AUTOLOSER_SEND_TIMEOUT = float(_env_int('LOSER_SEND_TIMEOUT', 25))."""
    if raw is None:
        monkeypatch.delenv("LOSER_SEND_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("LOSER_SEND_TIMEOUT", raw)
    assert _env_int("LOSER_SEND_TIMEOUT", 25) == expected
