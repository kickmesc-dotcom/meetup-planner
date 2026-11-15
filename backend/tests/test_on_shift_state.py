"""Состояние смены в панели «Сейчас на смене» (13.11.2026).

Правило одно, но ошибиться в нём легко: границы смены — это минуты, а не часы,
и «закончилась» наступает после конца, а не в момент конца. Проверяем границы
явно, потому что от них зависит, кого человек увидит в зале.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from app.api.routes_shifts import _minutes, _shift_state  # noqa: E402


def test_minutes_parse_and_guard_garbage() -> None:
    assert _minutes("10:00") == 600
    assert _minutes("23:45") == 1425
    assert _minutes(None) is None
    assert _minutes("") is None
    assert _minutes("мусор") is None
    assert _minutes("25:00") is None
    assert _minutes("12:99") is None


def test_state_boundaries() -> None:
    # 10:00–18:00, сейчас 14:00.
    assert _shift_state("10:00", "18:00", 14 * 60) == "on_shift"
    # Ровно начало — уже в смене.
    assert _shift_state("10:00", "18:00", 10 * 60) == "on_shift"
    # Ровно конец — ещё в смене: человек работает до этой минуты.
    assert _shift_state("10:00", "18:00", 18 * 60) == "on_shift"
    # Минутой позже — уже ушёл.
    assert _shift_state("10:00", "18:00", 18 * 60 + 1) == "finished"
    assert _shift_state("10:00", "18:00", 9 * 60) == "upcoming"


def test_without_hours_state_is_planned() -> None:
    """Без начала нельзя утверждать, что человек в смене."""
    assert _shift_state(None, "18:00", 14 * 60) == "planned"
    assert _shift_state("10:00", None, 14 * 60) == "on_shift"
