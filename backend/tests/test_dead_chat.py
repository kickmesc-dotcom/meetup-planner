"""GHG8 P7: пул шуток на «мёртвый чат».

Async-БД-стенда нет (зафиксированное ограничение) — кроем чистое ядро:
parse_phrases / parse_last_post / pick_threshold (эскалация + анти-спам) /
pick_phrase / env-таймаут (паттерн test_loser_send_timeout_env).
"""
from __future__ import annotations

import json
import random

import pytest

from app.services.dead_chat import (
    DEFAULT_PHRASES,
    THRESHOLDS,
    _send_timeout,
    parse_last_post,
    parse_phrases,
    pick_phrase,
    pick_threshold,
)

ACT_1 = "2026-06-01T10:00:00+00:00"  # окно тишины №1
ACT_2 = "2026-06-05T08:00:00+00:00"  # окно тишины №2 (новая активность)


# --- parse_phrases ---

def test_parse_none_gives_defaults_for_all_thresholds():
    out = parse_phrases(None)
    assert set(out) == {k for k, _ in THRESHOLDS}
    for key, _ in THRESHOLDS:
        assert out[key] == DEFAULT_PHRASES[key]
        assert out[key] is not DEFAULT_PHRASES[key]  # копия, не алиас


def test_parse_invalid_json_gives_defaults():
    assert parse_phrases("{oops") == parse_phrases(None)


def test_parse_custom_threshold_kept_others_default():
    raw = json.dumps({"24h": ["своя фраза"]})
    out = parse_phrases(raw)
    assert out["24h"] == ["своя фраза"]
    assert out["72h"] == DEFAULT_PHRASES["72h"]


def test_parse_empty_or_invalid_list_falls_back():
    # Пустой список и не-список строк → дефолт порога (паттерн loser_reasons:
    # кривая правка не оставляет бот немым).
    raw = json.dumps({"24h": [], "week": [1, 2], "year": "не список"})
    out = parse_phrases(raw)
    assert out["24h"] == DEFAULT_PHRASES["24h"]
    assert out["week"] == DEFAULT_PHRASES["week"]
    assert out["year"] == DEFAULT_PHRASES["year"]


def test_parse_strips_and_drops_blank_items():
    raw = json.dumps({"24h": ["  ok  ", "", "  "]})
    assert parse_phrases(raw)["24h"] == ["ok"]


def test_parse_unknown_threshold_ignored():
    raw = json.dumps({"5min": ["спам"], "24h": ["ок"]})
    out = parse_phrases(raw)
    assert "5min" not in out
    assert out["24h"] == ["ок"]


# --- parse_last_post ---

@pytest.mark.parametrize(
    "raw",
    [None, "{bad", "[]", json.dumps({"threshold": "5min", "activity_at": ACT_1}),
     json.dumps({"threshold": "24h"}), json.dumps({"activity_at": ACT_1})],
)
def test_parse_last_post_invalid(raw):
    assert parse_last_post(raw) is None


def test_parse_last_post_roundtrip():
    raw = json.dumps({"threshold": "week", "activity_at": ACT_1})
    assert parse_last_post(raw) == ("week", ACT_1)


# --- pick_threshold: достижение порогов ---

def test_below_first_threshold_silent():
    assert pick_threshold(23.9, None, ACT_1) is None


@pytest.mark.parametrize(
    "hours, expected",
    [
        (24.0, "24h"),
        (71.9, "24h"),
        (72.0, "72h"),
        (7 * 24.0, "week"),
        (30 * 24.0, "month"),
        (182 * 24.0, "half_year"),
        (365 * 24.0, "year"),
        (1000 * 24.0, "year"),  # глубже года порогов нет
    ],
)
def test_deepest_reached_threshold(hours, expected):
    assert pick_threshold(hours, None, ACT_1) == expected


def test_offline_skip_posts_once_at_deepest():
    # Бот был офлайн, тишина проскочила 24h и 72h → постим один раз по 72h,
    # не очередью из двух.
    assert pick_threshold(80.0, None, ACT_1) == "72h"


# --- pick_threshold: анти-спам в пределах окна тишины ---

def test_same_window_same_threshold_blocked():
    last = ("24h", ACT_1)
    assert pick_threshold(30.0, last, ACT_1) is None


def test_same_window_escalation_allowed():
    # 24h-пост не блокирует будущий 72h-пост в том же окне.
    last = ("24h", ACT_1)
    assert pick_threshold(73.0, last, ACT_1) == "72h"


def test_same_window_deeper_already_posted_blocks_shallow():
    # last_post глубже достигнутого (часы «откатиться» не могут, но защита
    # от рассинхрона значений) → молчим.
    last = ("week", ACT_1)
    assert pick_threshold(80.0, last, ACT_1) is None


def test_new_window_resets_antispam():
    # Новая активность → activity_at изменился → старый last_post не матчится,
    # 24h-порог постится снова.
    last = ("year", ACT_1)
    assert pick_threshold(25.0, last, ACT_2) == "24h"


# --- pick_phrase ---

def test_pick_phrase_from_pool():
    rng = random.Random(7)
    phrases = {"24h": ["a", "b", "c"]}
    assert pick_phrase(phrases, "24h", rng) in ("a", "b", "c")


def test_pick_phrase_empty_pool_none():
    assert pick_phrase({"24h": []}, "24h") is None
    assert pick_phrase({}, "24h") is None


# --- env-таймаут (паттерн test_loser_send_timeout_env) ---

@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, 25.0),
        ("25", 25.0),
        ("40", 40.0),
        ("0", 0.0),
        ("not-a-number", 25.0),
        ("12.5", 25.0),
        ("", 25.0),
    ],
)
def test_dead_chat_send_timeout_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("LOSER_SEND_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("LOSER_SEND_TIMEOUT", raw)
    assert _send_timeout() == expected


# --- дефолтные пулы: инварианты сидинга (P7.1.b) ---

def test_default_pools_nonempty_for_every_threshold():
    for key, _ in THRESHOLDS:
        assert DEFAULT_PHRASES[key], f"пустой дефолтный пул {key}"


def test_default_year_pool_keeps_user_quote():
    # Философская цитата пользователя из GHG7.txt стр. 201 — дословно.
    assert any("радиоактивные осадки" in p for p in DEFAULT_PHRASES["year"])
