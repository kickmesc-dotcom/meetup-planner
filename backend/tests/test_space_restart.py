"""GHG8 P14: рестарт HF Space — расписание + анти-луп.

Async-БД-стенда нет (зафиксированное ограничение) — кроем чистое ядро:
parse_schedule (клампы/fail-safe в off), compute_next_restart,
should_fire (анти-луп 30 мин, P14.3).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.services.space_restart import (
    EVERY_HOURS_MAX,
    EVERY_HOURS_MIN,
    MIN_RESTART_INTERVAL,
    compute_next_restart,
    parse_schedule,
    should_fire,
)

NOW = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
OFF = {"mode": "off", "at": None, "every_hours": None}


def _sched(mode: str, **kw) -> dict:
    return parse_schedule(json.dumps({"mode": mode, **kw}))


# --- parse_schedule ---

def test_parse_none_is_off():
    assert parse_schedule(None) == OFF


def test_parse_garbage_json_is_off():
    assert parse_schedule("{not json") == OFF
    assert parse_schedule('"string"') == OFF
    assert parse_schedule("[1,2]") == OFF


def test_parse_unknown_mode_is_off():
    assert parse_schedule('{"mode": "hourly"}') == OFF


def test_parse_once_valid():
    out = _sched("once", at="2026-06-09T10:00:00+00:00")
    assert out["mode"] == "once"
    assert out["at"] == "2026-06-09T10:00:00+00:00"
    assert out["every_hours"] is None


def test_parse_once_naive_datetime_gets_utc():
    out = _sched("once", at="2026-06-09T10:00:00")
    assert out["at"] == "2026-06-09T10:00:00+00:00"


def test_parse_once_z_suffix():
    out = _sched("once", at="2026-06-09T10:00:00Z")
    assert out["mode"] == "once"


def test_parse_once_without_at_degrades_to_off():
    assert _sched("once") == OFF
    assert _sched("once", at="чепуха") == OFF


def test_parse_interval_valid():
    out = _sched("interval", every_hours=24)
    assert out == {"mode": "interval", "at": None, "every_hours": 24}


def test_parse_interval_clamps_low_and_high():
    # P14.3: кламп в сеттере — ≥1ч (анти-луп) и ≤720ч.
    assert _sched("interval", every_hours=0)["every_hours"] == EVERY_HOURS_MIN
    assert _sched("interval", every_hours=-5)["every_hours"] == EVERY_HOURS_MIN
    assert _sched("interval", every_hours=9999)["every_hours"] == EVERY_HOURS_MAX


def test_parse_interval_without_hours_degrades_to_off():
    assert _sched("interval") == OFF
    assert _sched("interval", every_hours="кот") == OFF


# --- compute_next_restart ---

def test_next_off_is_none():
    assert compute_next_restart(OFF, None, NOW) is None
    assert compute_next_restart(OFF, NOW - timedelta(hours=1), NOW) is None


def test_next_once_is_at():
    sched = _sched("once", at="2026-06-09T10:00:00+00:00")
    assert compute_next_restart(sched, None, NOW) == datetime(
        2026, 6, 9, 10, 0, tzinfo=timezone.utc
    )


def test_next_interval_without_anchor_is_now():
    sched = _sched("interval", every_hours=24)
    assert compute_next_restart(sched, None, NOW) == NOW


def test_next_interval_is_anchor_plus_hours():
    sched = _sched("interval", every_hours=6)
    anchor = NOW - timedelta(hours=2)
    assert compute_next_restart(sched, anchor, NOW) == anchor + timedelta(hours=6)


# --- should_fire ---

def test_fire_off_never():
    assert not should_fire(OFF, None, NOW)


def test_fire_once_due():
    sched = _sched("once", at=(NOW - timedelta(minutes=1)).isoformat())
    assert should_fire(sched, None, NOW)


def test_fire_once_future_not_yet():
    sched = _sched("once", at=(NOW + timedelta(hours=1)).isoformat())
    assert not should_fire(sched, None, NOW)


def test_fire_interval_first_time_immediately():
    sched = _sched("interval", every_hours=24)
    assert should_fire(sched, None, NOW)


def test_fire_interval_respects_anchor():
    sched = _sched("interval", every_hours=24)
    assert not should_fire(sched, NOW - timedelta(hours=23), NOW)
    assert should_fire(sched, NOW - timedelta(hours=25), NOW)


def test_fire_antiloop_blocks_within_30_min():
    # P14.3: once в прошлом + ручной рестарт 10 мин назад → молчим.
    sched = _sched("once", at=(NOW - timedelta(hours=1)).isoformat())
    recent = NOW - timedelta(minutes=10)
    assert not should_fire(sched, recent, NOW)
    # Ровно на границе 30 мин — уже можно.
    edge = NOW - MIN_RESTART_INTERVAL
    assert should_fire(sched, edge, NOW)
