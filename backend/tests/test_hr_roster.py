"""Снапшоты состава: правила, которые видит администратор (без БД).

Здесь проверяется то, что легко сломать незаметно: разбор Telegram-ID из поля
ввода (человек копирует ID с пробелами и `@`), защита синтетического диапазона
демо-пула и то, что запись снимка остаётся обычным JSON — иначе PostgreSQL
откажется её принимать, а ошибка всплывёт только на живой базе.
"""

from __future__ import annotations

import json
import os
from datetime import date

import pytest

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("ADMIN_TG_IDS", "")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from app.db.hr_models import ROLE_ADMIN, ROLE_EMPLOYEE  # noqa: E402
from app.services import hr_demo, hr_roster  # noqa: E402


def test_telegram_id_is_read_from_pasted_text() -> None:
    assert hr_roster.normalize_telegram_id("123456789") == 123456789
    assert hr_roster.normalize_telegram_id("  123 456 789 ") == 123456789
    assert hr_roster.normalize_telegram_id("@123456789") == 123456789
    assert hr_roster.normalize_telegram_id("123\u00a0456") == 123456


@pytest.mark.parametrize("raw", ["", "   ", "abc", "12a", "-5", "0", "0.5"])
def test_broken_telegram_id_is_rejected(raw: str) -> None:
    with pytest.raises(hr_roster.RosterError) as exc:
        hr_roster.normalize_telegram_id(raw)
    assert str(exc.value) == "bad_telegram_id"


def test_demo_range_cannot_be_claimed_manually() -> None:
    """Синтетические ID пула заняты: настоящий человек не должен их получить."""
    with pytest.raises(hr_roster.RosterError) as exc:
        hr_roster.normalize_telegram_id(str(hr_demo.DEMO_TG_BASE))
    assert str(exc.value) == "demo_id_reserved"


def test_bool_is_not_a_telegram_id() -> None:
    """`True` — подкласс `int`, и без проверки он стал бы ID 1."""
    with pytest.raises(hr_roster.RosterError):
        hr_roster.normalize_telegram_id(True)


def test_missing_name_gets_a_readable_default() -> None:
    assert hr_roster.clean_name(None, 777) == "ID 777"
    assert hr_roster.clean_name("   ", 777) == "ID 777"
    assert hr_roster.clean_name("  Аня  ", 777) == "Аня"


def test_label_is_trimmed_to_the_column_width() -> None:
    assert hr_roster.clean_label("  перед чисткой  ") == "перед чисткой"
    assert len(hr_roster.clean_label("я" * 500)) == 120
    assert hr_roster.clean_label(None) == ""


def test_person_entry_is_json_and_sanitizes_unknown_values() -> None:
    entry = hr_roster.person_entry(
        telegram_id=42,
        display_name="Аня",
        username="anya",
        position="повар",
        badge=None,
        badge_emoji=None,
        department_slug="cook",
        department_name="Кухня",
        role="владелец вселенной",
        onboarding_state="неизвестно",
        is_demo=False,
        is_active=True,
        hire_date=date(2026, 10, 1),
    )
    # Снимок живёт в JSONB — значит, обязан сериализоваться без объектов.
    assert json.loads(json.dumps(entry))["telegram_id"] == 42
    # Неизвестная роль не должна давать доступ выше сотрудника.
    assert entry["role"] == ROLE_EMPLOYEE
    assert entry["onboarding_state"] == "new"
    assert entry["hire_date"] == "2026-10-01"


def test_known_role_is_preserved_in_snapshot() -> None:
    entry = hr_roster.person_entry(
        telegram_id=1,
        display_name="Босс",
        username=None,
        position=None,
        badge=None,
        badge_emoji=None,
        department_slug=None,
        department_name=None,
        role=ROLE_ADMIN,
        onboarding_state="done",
        is_demo=False,
        is_active=True,
    )
    assert entry["role"] == ROLE_ADMIN
    assert entry["hire_date"] is None


def test_hire_date_parser_tolerates_garbage() -> None:
    assert hr_roster.parse_hire_date("2026-02-03") == date(2026, 2, 3)
    assert hr_roster.parse_hire_date(date(2026, 2, 3)) == date(2026, 2, 3)
    assert hr_roster.parse_hire_date("03.02.2026") is None
    assert hr_roster.parse_hire_date(None) is None
