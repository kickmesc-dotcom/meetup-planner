"""GHG8 P2.4: «Пост от лица бота» / «Пост от своего имени» в ДР-поповере.

Бэк: POST /api/birthdays/{user_id}/greeting/post — публикует текст из
textarea в группу. `signed=True` дописывает «— Поздравил {имя}» (отправка
от лица юзера в TG невозможна без UserBot — подпись честная замена).

Async-БД-стенда нет (зафиксированное ограничение) — кроем чистые функции:
compose_greeting_post и env-парсер таймаута (паттерн test_loser_send_timeout_env).
"""
from __future__ import annotations

import pytest

from app.api.routes_birthdays import (
    _GREETING_MAX_LEN,
    GreetingPostIn,
    _greeting_send_timeout,
    compose_greeting_post,
)


def test_compose_unsigned_passthrough():
    assert compose_greeting_post("С др, бро!", signed_by=None) == "С др, бро!"


def test_compose_strips_whitespace():
    assert compose_greeting_post("  текст \n", signed_by=None) == "текст"


def test_compose_signed_appends_author():
    out = compose_greeting_post("С др!", signed_by="Никита")
    assert out == "С др!\n\n— Поздравил Никита"


def test_compose_signed_after_strip():
    # Подпись клеится к уже-обрезанному тексту — без хвостовых пробелов перед ней.
    out = compose_greeting_post("С др!\n\n", signed_by="Сергей Neo")
    assert out == "С др!\n\n— Поздравил Сергей Neo"


def test_compose_keeps_html_specials_as_is():
    # parse_mode не используем — <, & и {} уходят в TG как есть, не ломая send.
    text = "Поздравляю <3 & жди {подарок}"
    assert compose_greeting_post(text, signed_by=None) == text


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, 25.0),            # не задан → дефолт
        ("25", 25.0),            # дефолт явно
        ("40", 40.0),            # кастомное число
        ("0", 0.0),              # граничный 0 — валиден
        ("not-a-number", 25.0),  # мусор → фолбэк
        ("12.5", 25.0),          # float-строка не int → фолбэк
        ("", 25.0),              # пустая строка → фолбэк
    ],
)
def test_greeting_send_timeout_env(monkeypatch, raw, expected):
    """Зеркало routes_meetings._loser_send_timeout — общий env LOSER_SEND_TIMEOUT."""
    if raw is None:
        monkeypatch.delenv("LOSER_SEND_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("LOSER_SEND_TIMEOUT", raw)
    result = _greeting_send_timeout()
    assert result == expected
    assert isinstance(result, float)


def test_post_in_rejects_empty_text():
    with pytest.raises(Exception):
        GreetingPostIn(text="")


def test_post_in_rejects_overlong_text():
    with pytest.raises(Exception):
        GreetingPostIn(text="x" * (_GREETING_MAX_LEN + 1))


def test_post_in_defaults_unsigned():
    assert GreetingPostIn(text="ok").signed is False
