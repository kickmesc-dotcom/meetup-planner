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
    p2 = UiPrefsPatch(hide_greeting=True)
    assert p2.hide_greeting is True and p2.welcome_format is None


# --- P4.1.d: /top в каталоге команд ---

def test_top_command_in_catalog():
    top = next((c for c in COMMANDS if c.cmd == "top"), None)
    assert top is not None, "/top отсутствует в каталоге"
    assert top.scope == "both"
    assert not top.admin_only
