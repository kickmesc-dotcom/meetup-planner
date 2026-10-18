"""Имена сотрудников: сборка из Telegram и починка испорченных записей.

Отдельный тест, потому что баг с «ромбиками» — не косметика: имя уезжает в
списки сотрудников, фильтры ленты и уведомления. Восстановить U+FFFD обратным
декодированием нельзя, поэтому проверяем две вещи: битое значение никогда не
подставляется и известное каноническое имя важнее пустого.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from app.db.hr_seed import OWNERS  # noqa: E402
from app.services import display_names  # noqa: E402

BROKEN = "\ufffd\ufffd\ufffd-NEO"


def test_replacement_char_is_detected() -> None:
    assert display_names.is_corrupted(BROKEN) is True
    assert display_names.is_corrupted("Серж-NEO") is False
    assert display_names.is_corrupted(None) is False
    assert display_names.is_corrupted("") is False


def test_corrupted_parts_are_never_used() -> None:
    name = display_names.compose_display_name(BROKEN, "Управляющий", "boss")
    assert name == "Управляющий"
    assert "\ufffd" not in name


def test_clean_name_wins_over_username() -> None:
    assert display_names.compose_display_name("Дмитрий", "Ковалёв", "dm") == "Дмитрий Ковалёв"
    assert display_names.compose_display_name("", None, "dm") == "dm"


def test_fallback_when_everything_is_broken() -> None:
    assert (
        display_names.compose_display_name(BROKEN, BROKEN, None, fallback_id=42)
        == "Сотрудник 42"
    )
    assert display_names.compose_display_name(None, None, None) == "Сотрудник"


def test_owner_names_are_clean() -> None:
    """Сид владельцев — последний рубеж: он не должен сам приносить «ромбики»."""
    for tg_id, name, _emoji, _badge in OWNERS:
        assert not display_names.is_corrupted(name), (tg_id, name)
        assert display_names.has_text(name)
