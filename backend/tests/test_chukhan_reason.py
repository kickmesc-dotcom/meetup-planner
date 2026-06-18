"""GHG8 T1.2: тесты префикса «Причина:» в анонсе чухана.

Покрывает чистый _format_announcement (без БД/сети). Персист reason_text на
WeeklyChukhan и проброс в историю проверяются вручную (async-БД-стенда в
проекте нет — паттерн test_posting_alerts).
"""
from __future__ import annotations

from app.db.models import User
from app.services.chukhan import CHUKHAN_TAGLINES, _format_announcement


def _user() -> User:
    return User(id=1, telegram_id=42, display_name="Серж", username="serge")


def test_explicit_reason_has_prefix():
    text = _format_announcement(_user(), reason="облажался по полной")
    assert "<i>Причина: облажался по полной</i>" in text


def test_default_reason_also_prefixed():
    # Без явной фразы берётся случайный CHUKHAN_TAGLINE — он тоже под префиксом.
    text = _format_announcement(_user())
    assert "Причина: " in text
    chosen = text.split("Причина: ", 1)[1].rstrip("</i>")
    assert any(chosen == t for t in CHUKHAN_TAGLINES)


def test_reason_appears_once():
    text = _format_announcement(_user(), reason="двойной чухан")
    assert text.count("Причина:") == 1


def test_handle_falls_back_to_name_without_username():
    u = User(id=2, telegram_id=7, display_name="Безюзернейма", username=None)
    text = _format_announcement(u, reason="x")
    # handle == name, без @ — имя присутствует и в шапке, и в скобках.
    assert "(Безюзернейма)" in text
