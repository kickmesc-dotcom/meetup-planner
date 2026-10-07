"""GHG8 P4: welcome-screen prefs + /top в каталоге команд.

Async-БД-стенда нет (см. test_titles_current) — get/set_ui_welcome_format
не дёргаем; тестируем чистое: валидацию формата (константы + pydantic-pattern
PATCH-схемы) и присутствие /top в каталоге.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routes_users import UiPrefsPatch
from app.bot.commands_catalog import COMMANDS
from app.services.admin_config import WELCOME_FORMATS, _WELCOME_FORMAT_DEFAULT


# --- P4.1.b: единый формат отображения ---

def test_welcome_formats_expected_set():
    # Спека (GHG7.txt стр. 26–27): имя | аватарка | имя+аватарка.
    assert set(WELCOME_FORMATS) == {"name", "avatar", "both"}


def test_welcome_format_default_is_avatar():
    # «по умолчанию — аватарка» (спека).
    assert _WELCOME_FORMAT_DEFAULT == "avatar"
    assert _WELCOME_FORMAT_DEFAULT in WELCOME_FORMATS


@pytest.mark.parametrize("fmt", ["name", "avatar", "both"])
def test_ui_prefs_patch_accepts_valid_formats(fmt):
    assert UiPrefsPatch(welcome_format=fmt).welcome_format == fmt


@pytest.mark.parametrize("fmt", ["", "Avatar", "name+avatar", "emoji", "none"])
def test_ui_prefs_patch_rejects_invalid_formats(fmt):
    with pytest.raises(ValidationError):
        UiPrefsPatch(welcome_format=fmt)


def test_ui_prefs_patch_all_fields_optional():
    # Старые клиенты шлют {hide_greeting} без формата — совместимость.
    p = UiPrefsPatch()
    assert p.hide_greeting is None and p.welcome_format is None
    assert p.muted_feed is None
    p2 = UiPrefsPatch(hide_greeting=True)
    assert p2.hide_greeting is True and p2.welcome_format is None


# --- GHG11(7): персональный фильтр ленты «по участникам» ---

def test_ui_prefs_patch_accepts_muted_feed():
    assert UiPrefsPatch(muted_feed=[2, 5]).muted_feed == [2, 5]


@pytest.mark.asyncio
async def test_muted_feed_storage_roundtrip(monkeypatch):
    """Список хранится строкой id через запятую и разбирается обратно."""
    from app.services import admin_config as ac

    store: dict[str, str] = {}

    async def fake_get(session, key):
        return store.get(key)

    async def fake_set(session, key, value):
        store[key] = value

    monkeypatch.setattr(ac, "_get_value", fake_get)
    monkeypatch.setattr(ac, "_set_value", fake_set)

    assert await ac.get_ui_muted_feed(None, 777) == set()
    await ac.set_ui_muted_feed(None, 777, {7, 3, 3})
    assert store["ui.muted_feed:777"] == "3,7"
    assert await ac.get_ui_muted_feed(None, 777) == {3, 7}

    # Мусор в значении не роняет парсер.
    store["ui.muted_feed:778"] = "3, x, 5"
    assert await ac.get_ui_muted_feed(None, 778) == {3, 5}


# --- P4.1.d: /top в каталоге команд ---

def test_top_command_in_catalog():
    top = next((c for c in COMMANDS if c.cmd == "top"), None)
    assert top is not None, "/top отсутствует в каталоге"
    assert top.scope == "both"
    assert not top.admin_only
