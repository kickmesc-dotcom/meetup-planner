"""Тесты для GHG6 BD2: render_greeting + склонение возраста."""
from __future__ import annotations

from app.api.routes_birthdays import _age_phrase, render_greeting


def test_age_phrase_year_unknown():
    age_text, phrase, fallback = _age_phrase(None)
    assert age_text == ""
    assert phrase == ""
    assert fallback == "новый год жизни"


def test_age_phrase_basic_cases():
    # Стандартные RU-склонения числительных.
    assert _age_phrase(1)[0] == "1 год"
    assert _age_phrase(2)[0] == "2 года"
    assert _age_phrase(4)[0] == "4 года"
    assert _age_phrase(5)[0] == "5 лет"
    assert _age_phrase(11)[0] == "11 лет"   # 11..14 — лет
    assert _age_phrase(12)[0] == "12 лет"
    assert _age_phrase(14)[0] == "14 лет"
    assert _age_phrase(21)[0] == "21 год"
    assert _age_phrase(22)[0] == "22 года"
    assert _age_phrase(25)[0] == "25 лет"
    assert _age_phrase(100)[0] == "100 лет"
    assert _age_phrase(101)[0] == "101 год"
    assert _age_phrase(111)[0] == "111 лет"


def test_render_replaces_name():
    out = render_greeting("Привет, {name}!", name="Никита", age=None)
    assert out == "Привет, Никита!"


def test_render_replaces_age_when_known():
    out = render_greeting("{name}, тебе {age}!", name="Сергей", age=30)
    assert out == "Сергей, тебе 30 лет!"


def test_render_age_phrase_empty_when_unknown():
    out = render_greeting("{name}, поздравляю! {age_phrase}", name="Дима", age=None)
    assert out == "Дима, поздравляю! "


def test_render_age_or_year_fallback():
    # Когда возраст неизвестен — `{age_or_year}` подставляет фразу-плейсхолдер.
    out = render_greeting("Пусть {age_or_year} будет лучшим!", name="-", age=None)
    assert out == "Пусть новый год жизни будет лучшим!"


def test_render_age_or_year_uses_age_when_known():
    out = render_greeting("Пусть {age_or_year} будет лучшим!", name="-", age=30)
    assert out == "Пусть 30 лет будет лучшим!"


def test_render_ignores_unknown_placeholders():
    # `{foo}` оставляем как есть — не падаем на .format ловушке.
    out = render_greeting("{name} {foo} {bar}", name="Дима", age=None)
    assert out == "Дима {foo} {bar}"
