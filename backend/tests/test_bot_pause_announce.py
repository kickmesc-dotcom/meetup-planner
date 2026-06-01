"""GHG7 P2.2 — анонсы паузы бота в группу.

Тестируем чистую логику без БД/Telegram (тот же паттерн, что test_bot_pause):
- какие фразы возвращения существуют;
- предикат «анонсить ли возвращение» (матрица пауза_способ × снятие_способ);
- расчёт длительности отсутствия в часах.

Реальная отправка в группу (send_message) и интеграция с scheduler-тиком
проверяются руками на стенде после деплоя — async-БД-стенда в проекте нет.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.bot_pause import (
    CHAT_INITIATED_REASONS,
    VALID_REASONS,
    _format_absence_hours,
    should_announce_restore,
)
from app.services.zaebal import WELCOME_BACK_PHRASES, _welcome_back_phrase


# --- фразы возвращения ---


def test_welcome_back_phrase_from_pool() -> None:
    assert _welcome_back_phrase() in WELCOME_BACK_PHRASES


def test_welcome_back_pool_nonempty_strings() -> None:
    assert WELCOME_BACK_PHRASES
    assert all(isinstance(p, str) and p.strip() for p in WELCOME_BACK_PHRASES)


# --- матрица: анонсить ли возвращение ---


def test_announce_only_for_chat_reasons_when_automatic() -> None:
    """Авто-разморозка (announce=True): анонс только для chat-инициированных
    причин, manual_admin — молча."""
    assert should_announce_restore("zaebal_threshold", announce=True) is True
    assert should_announce_restore("zaebal_vote", announce=True) is True
    assert should_announce_restore("auto_monthly", announce=True) is True
    assert should_announce_restore("manual_admin", announce=True) is False


def test_no_announce_when_manual_stop() -> None:
    """Ручное снятие (announce=False) — silent для ЛЮБОЙ причины, включая
    chat-инициированные (snяли через админку/zaebal_undo)."""
    for reason in VALID_REASONS:
        assert should_announce_restore(reason, announce=False) is False


def test_chat_initiated_reasons_subset_of_valid() -> None:
    """Гард: chat-инициированные причины — подмножество валидных, и
    manual_admin в них НЕ входит."""
    assert CHAT_INITIATED_REASONS <= VALID_REASONS
    assert "manual_admin" not in CHAT_INITIATED_REASONS


# --- расчёт часов отсутствия ---


def test_absence_hours_rounds_to_nearest() -> None:
    started = datetime(2026, 5, 31, 10, 0, 0, tzinfo=timezone.utc)
    assert _format_absence_hours(started, started + timedelta(hours=3)) == 3
    # 3ч40м → округляется к 4
    assert _format_absence_hours(started, started + timedelta(hours=3, minutes=40)) == 4
    # 72ч (3 дня) — типичная zaebal-пауза
    assert _format_absence_hours(started, started + timedelta(days=3)) == 72


def test_absence_hours_minimum_one() -> None:
    """Короткая/нулевая пауза → минимум «1 ч», чтобы не писать «0 ч»."""
    started = datetime(2026, 5, 31, 10, 0, 0, tzinfo=timezone.utc)
    assert _format_absence_hours(started, started) == 1
    assert _format_absence_hours(started, started + timedelta(minutes=10)) == 1


def test_absence_hours_tolerates_naive_started_at() -> None:
    """Драйвер может вернуть started_at без tzinfo — считаем его UTC, без падения."""
    started_naive = datetime(2026, 5, 31, 10, 0, 0)  # naive
    ended = datetime(2026, 5, 31, 13, 0, 0, tzinfo=timezone.utc)
    assert _format_absence_hours(started_naive, ended) == 3
