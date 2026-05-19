"""Тесты для GHG6 PL5/PL6: parse_option и _fmt_option date-only."""
from __future__ import annotations

from datetime import date, datetime

from app.services.polls import _fmt_option, _parse_option


def test_parse_date_only_string():
    dt, has_time = _parse_option("2026-05-17")
    assert dt == datetime(2026, 5, 17, 0, 0)
    assert has_time is False


def test_parse_iso_datetime_string():
    dt, has_time = _parse_option("2026-05-17T20:00:00")
    assert dt == datetime(2026, 5, 17, 20, 0, 0)
    assert has_time is True


def test_parse_iso_datetime_with_z():
    dt, has_time = _parse_option("2026-05-17T20:00:00Z")
    assert dt.year == 2026 and dt.hour == 20
    assert has_time is True


def test_parse_date_object():
    dt, has_time = _parse_option(date(2026, 5, 17))
    assert dt == datetime(2026, 5, 17, 0, 0)
    assert has_time is False


def test_parse_datetime_object():
    src = datetime(2026, 5, 17, 19, 30)
    dt, has_time = _parse_option(src)
    assert dt == src
    assert has_time is True


def test_fmt_option_with_time():
    # 2026-05-17 — это воскресенье
    dt = datetime(2026, 5, 17, 20, 0)
    assert _fmt_option(dt, has_time=True) == "Вс 17.05 20:00"


def test_fmt_option_date_only():
    dt = datetime(2026, 5, 17, 0, 0)
    assert _fmt_option(dt, has_time=False) == "Вс 17.05"
