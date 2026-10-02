"""Э19: передача червя — разбор подтверждения и каталог «весёлых» ачивок.

Сетевого/БД-стенда нет: проверяем чистую логику (`parse_confirmation`), состав
каталога и то, что новые ачивки легли в раздел «Червь-господин».
"""
from __future__ import annotations

import pytest

from app.services.game import worm_transfer
from app.services.game.achievements_catalog import get, group_of


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("да", True),
        ("Да!", True),
        ("ага", True),
        ("Ок.", True),
        ("yes", True),
        ("+", True),
        ("нет", False),
        ("Нет.", False),
        ("no", False),
        ("отмена", False),
        ("-", False),
        ("может быть", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_confirmation(text, expected):
    assert worm_transfer.parse_confirmation(text) is expected


def test_worm_transfer_achievements_are_grouped():
    for code in ("punish_day3", "punish_all", "punish_bot"):
        assert get(code) is not None, code
        assert group_of(code)[0] == "worm_master", code


def test_transfer_notice_mentions_command():
    assert "/worm" in worm_transfer.TRANSFER_NOTICE_TEXT
    assert "да" in worm_transfer.TRANSFER_NOTICE_TEXT
