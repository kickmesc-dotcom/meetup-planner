"""GHG8 Q7: persist «последнего медиа» + таймаут TG-вызовов медиа-подсистемы.

Q7.a — `_media_send_timeout` (env LOSER_SEND_TIMEOUT, паттерн
test_loser_send_timeout_env): без обёртки send/me() висели на 30с-таймауте
сессии бота и блокировали webhook-хендлер на ~32с (memefail).

Q7.b — `parse_recent_media`: чистый парсер JSON-значения
`media_reactions.recent_media` из admin_config. In-memory `_recent` хендлера
обнуляется при рестарте Space — БД-копия переживает, force-кнопки работают.
Async-БД-стенда в проекте нет — get/save (обёртки над _get/_set_value)
тестируются только через парсер.
"""
from __future__ import annotations

import json

import pytest

from app.bot.handlers.media_reactions import _media_send_timeout
from app.services.media_reactions import parse_recent_media


# --- Q7.a: env-таймаут ---

@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, 25.0),            # не задан → дефолт
        ("25", 25.0),            # дефолтное значение явно
        ("40", 40.0),            # кастомное число
        ("0", 0.0),              # граничный 0 — валиден, парсится
        ("not-a-number", 25.0),  # мусор → фолбэк
        ("12.5", 25.0),          # float-строка не int → фолбэк (env целочисленный)
        ("", 25.0),              # пустая строка → фолбэк
    ],
)
def test_media_send_timeout_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("LOSER_SEND_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("LOSER_SEND_TIMEOUT", raw)
    result = _media_send_timeout()
    assert result == expected
    assert isinstance(result, float)


# --- Q7.b: парсер персистнутого «последнего медиа» ---

def _payload(**chats) -> str:
    return json.dumps(chats, ensure_ascii=False)


def test_parse_none_and_invalid_json_give_empty():
    assert parse_recent_media(None) == {}
    assert parse_recent_media("") == {}
    assert parse_recent_media("{broken json") == {}
    assert parse_recent_media("[1, 2, 3]") == {}  # не dict


def test_parse_valid_single_record():
    raw = _payload(**{"-100123": {"kind": "single", "message_id": 77, "author_name": "Митян"}})
    assert parse_recent_media(raw) == {-100123: ("single", 77, "Митян")}


def test_parse_multiple_chats_and_kinds():
    raw = _payload(
        **{
            "-1001": {"kind": "single", "message_id": 1, "author_name": "A"},
            "-1002": {"kind": "collection", "message_id": 2, "author_name": "B"},
        }
    )
    parsed = parse_recent_media(raw)
    assert parsed[-1001] == ("single", 1, "A")
    assert parsed[-1002] == ("collection", 2, "B")


def test_parse_skips_invalid_records_keeps_valid():
    raw = _payload(
        **{
            "not-an-int": {"kind": "single", "message_id": 1, "author_name": "X"},
            "-1001": {"kind": "bogus", "message_id": 1, "author_name": "X"},
            "-1002": {"kind": "single", "message_id": "not-int", "author_name": "X"},
            "-1003": "not-a-dict",
            "-1004": {"kind": "collection", "message_id": 9, "author_name": "OK"},
        }
    )
    assert parse_recent_media(raw) == {-1004: ("collection", 9, "OK")}


def test_parse_author_name_fallbacks_to_empty():
    # author_name отсутствует или не-строка → "" (фраза без имени осмысленна).
    raw = _payload(
        **{
            "-1001": {"kind": "single", "message_id": 5},
            "-1002": {"kind": "single", "message_id": 6, "author_name": 123},
        }
    )
    parsed = parse_recent_media(raw)
    assert parsed[-1001] == ("single", 5, "")
    assert parsed[-1002] == ("single", 6, "")


def test_roundtrip_save_format():
    """Формат, который пишет save_recent_media, читается парсером без потерь."""
    stored = {-100555: ("collection", 42, "Дрон")}
    payload = {
        str(cid): {"kind": k, "message_id": mid, "author_name": name}
        for cid, (k, mid, name) in stored.items()
    }
    assert parse_recent_media(json.dumps(payload, ensure_ascii=False)) == stored
