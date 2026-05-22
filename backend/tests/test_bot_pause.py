"""GHG6 E11 — чистая логика snapshot/restore и zaebal-голосов.

Интеграция с БД (UNIQUE singleton, scheduler reload) не тестируется юнитами
по тому же паттерну, что и worm: в проекте нет async-sqlite-стенда, тестируем
только чистые функции. Реальный сценарий «запустил паузу → токгглы выключились →
снял → восстановилось» проверяется руками на стенде после деплоя.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.bot_pause import apply_pause_overrides, build_snapshot
from app.services.zaebal import (
    count_unique_voters_in_window,
    decide_zaebal_poll_outcome,
)


def _now() -> datetime:
    return datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)


# --- build_snapshot / apply_pause_overrides ---


def test_build_snapshot_packs_three_blocks() -> None:
    snap = build_snapshot(
        scheduled={"reminders": {"enabled": True, "tick_minutes": 5}},
        reactions={
            "mention_enabled": True,
            "reply_all_enabled": False,
            "reply_except_phrases_enabled": True,
        },
        zaebal={"auto_enabled": True, "threshold": 2},
    )
    assert snap["scheduled"]["reminders"]["enabled"] is True
    assert snap["reactions"]["mention_enabled"] is True
    assert snap["zaebal"]["auto_enabled"] is True


def test_apply_pause_overrides_flips_enabled_flags() -> None:
    snap = build_snapshot(
        scheduled={
            "reminders": {"enabled": True, "tick_minutes": 5},
            "loser": {"enabled": True, "per_day": 3, "window_start_hour": 9},
            "phrases": {"enabled": True, "window_start": "10:00", "window_end": "22:00"},
            "avatars": {"enabled": True, "per_day": 1.0},
            "birthdays": {"alerts_enabled": True},
            "chukhan": {"weekday": 0},
        },
        reactions={
            "mention_enabled": True,
            "reply_all_enabled": True,
            "reply_except_phrases_enabled": True,
        },
        zaebal={"auto_enabled": True, "threshold": 2},
    )
    over = apply_pause_overrides(snap)
    assert over["scheduled"]["reminders"]["enabled"] is False
    assert over["scheduled"]["loser"]["enabled"] is False
    assert over["scheduled"]["phrases"]["enabled"] is False
    assert over["scheduled"]["avatars"]["enabled"] is False
    assert over["scheduled"]["birthdays"]["alerts_enabled"] is False
    assert over["reactions"]["mention_enabled"] is False
    assert over["reactions"]["reply_all_enabled"] is False
    assert over["reactions"]["reply_except_phrases_enabled"] is False
    assert over["zaebal"]["auto_enabled"] is False
    # Числовые остаются как были — не превращаем в дефолты.
    assert over["scheduled"]["loser"]["per_day"] == 3
    assert over["scheduled"]["loser"]["window_start_hour"] == 9


def test_apply_pause_overrides_zeros_all_reply_toggles() -> None:
    """Под паузой выключаются ОБА reply-тогла. Восстановление пройдёт из
    snapshot, который мы сохранили перед паузой — пользовательский выбор
    не теряется."""
    snap = build_snapshot(
        scheduled={"reminders": {"enabled": True, "tick_minutes": 5}},
        reactions={
            "mention_enabled": True,
            "reply_all_enabled": True,
            "reply_except_phrases_enabled": True,
        },
        zaebal={},
    )
    over = apply_pause_overrides(snap)
    assert over["reactions"]["reply_all_enabled"] is False
    assert over["reactions"]["reply_except_phrases_enabled"] is False
    # snapshot оригиналов остался прежним — restore вернёт исходные значения
    assert snap["reactions"]["reply_all_enabled"] is True
    assert snap["reactions"]["reply_except_phrases_enabled"] is True


# --- zaebal: голоса в окне ---


def test_zaebal_window_unique_voters() -> None:
    now = _now()
    votes = [
        {"ts": (now - timedelta(minutes=30)).isoformat(), "tg_id": 1},
        {"ts": (now - timedelta(minutes=10)).isoformat(), "tg_id": 2},
        {"ts": (now - timedelta(minutes=70)).isoformat(), "tg_id": 3},  # за окном
        {"ts": (now - timedelta(minutes=5)).isoformat(), "tg_id": 1},   # дубль 1 → 1 уникальный
    ]
    unique = count_unique_voters_in_window(votes, now, 60)
    assert unique == {1, 2}


def test_zaebal_window_handles_garbage() -> None:
    """Битые записи (нет ts, кривой формат) пропускаются без падения."""
    now = _now()
    votes = [
        {"tg_id": 1},                              # нет ts
        {"ts": "not-a-date", "tg_id": 2},          # битый ts
        {"ts": now.isoformat()},                   # нет tg_id
        {"ts": now.isoformat(), "tg_id": "abc"},  # tg_id строка, не int
        {"ts": now.isoformat(), "tg_id": 42},      # ОК
    ]
    unique = count_unique_voters_in_window(votes, now, 60)
    assert unique == {42}


def test_zaebal_empty_buffer() -> None:
    assert count_unique_voters_in_window([], _now(), 60) == set()


# --- zaebal poll outcome ---


def test_zaebal_poll_majority_yes() -> None:
    assert decide_zaebal_poll_outcome(yes_votes=3, no_votes=2) is True


def test_zaebal_poll_majority_no() -> None:
    assert decide_zaebal_poll_outcome(yes_votes=2, no_votes=3) is False


def test_zaebal_poll_tie_loses() -> None:
    """Ничья — не приостанавливаем (требуется большинство, не равенство)."""
    assert decide_zaebal_poll_outcome(yes_votes=2, no_votes=2) is False


def test_zaebal_poll_zero_votes_loses() -> None:
    assert decide_zaebal_poll_outcome(yes_votes=0, no_votes=0) is False
