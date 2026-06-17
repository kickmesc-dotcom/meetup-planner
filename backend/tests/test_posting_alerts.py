"""GHG8 T3.3: тесты чистого ядра алёртов постинга (без БД).

Покрывает is_chukhan_overdue (порог форы, posted/fresh/None) и summarize
(агрегат total). get_posting_alerts ходит в БД — тестируется вручную
(async-БД-стенда в проекте нет).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.posting_alerts import (
    CHUKHAN_OVERDUE_AFTER,
    is_chukhan_overdue,
    summarize,
)

NOW = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)


def test_posted_chukhan_is_never_overdue():
    # posted_at задан → доставлен, не алёрт (даже если создан давно).
    assert not is_chukhan_overdue(NOW - timedelta(days=2), NOW, now=NOW)


def test_fresh_unposted_not_overdue():
    # Создан 10 минут назад, фора час → ещё рано алёртить.
    assert not is_chukhan_overdue(NOW - timedelta(minutes=10), None, now=NOW)


def test_overdue_unposted_is_alert():
    assert is_chukhan_overdue(NOW - timedelta(hours=2), None, now=NOW)


def test_exactly_at_threshold_is_overdue():
    assert is_chukhan_overdue(NOW - CHUKHAN_OVERDUE_AFTER, None, now=NOW)


def test_just_under_threshold_not_overdue():
    assert not is_chukhan_overdue(
        NOW - CHUKHAN_OVERDUE_AFTER + timedelta(minutes=1), None, now=NOW
    )


def test_none_created_at_not_overdue():
    assert not is_chukhan_overdue(None, None, now=NOW)


def test_naive_created_at_treated_as_utc():
    # created_at без tzinfo не должен ронять сравнение.
    naive = (NOW - timedelta(hours=2)).replace(tzinfo=None)
    assert is_chukhan_overdue(naive, None, now=NOW)


def test_custom_grace():
    created = NOW - timedelta(minutes=20)
    assert not is_chukhan_overdue(created, None, now=NOW)  # дефолт час
    assert is_chukhan_overdue(
        created, None, now=NOW, grace=timedelta(minutes=15)
    )


def test_summarize_counts_total():
    assert summarize([], None) == {"total": 0, "loser": [], "chukhan": None}
    assert summarize([{"x": 1}], None)["total"] == 1
    assert summarize([], {"week_start": "w"})["total"] == 1
    assert summarize([{"x": 1}, {"y": 2}], {"week_start": "w"})["total"] == 3


def test_summarize_passes_through_payloads():
    loser = [{"outbox_id": 5}]
    chukhan = {"user_name": "Серж"}
    out = summarize(loser, chukhan)
    assert out["loser"] is loser
    assert out["chukhan"] is chukhan
