"""Язык текста ленты смены (24.10.2026).

Почему отдельный тест на такую мелочь. Фразу записи собирает сервер, а не
интерфейс, поэтому английская локаль ломается не «где-то в вёрстке», а здесь:
забыли шаблон — и в английской ленте появляется русская строка посреди
английского интерфейса. Проверяем три свойства: русский остаётся русским,
известный шаблон переводится, неизвестный (своё содержимое) не ломается.
"""
from __future__ import annotations

from app.services import hr_feed


def test_russian_by_default() -> None:
    assert (
        hr_feed.say("ru", "отметил(а) пункт «{title}»", title="Поднять жалюзи")
        == "отметил(а) пункт «Поднять жалюзи»"
    )


def test_english_template() -> None:
    assert (
        hr_feed.say("en", "отметил(а) пункт «{title}»", title="Поднять жалюзи")
        == "ticked the item “Поднять жалюзи”"
    )


def test_status_with_action() -> None:
    action = hr_feed.say("en", "выполнил(а) поручение")
    text = hr_feed.say(
        "en", "{action}: «{title}»", action=action, title="Проверить витрину"
    )
    assert text == "completed the task: “Проверить витрину”"


def test_unknown_template_stays_as_is() -> None:
    # Своё содержимое (название пункта, поручения) не переводится — и это
    # нормально: показываем как написали, а не пустую строку и не ключ.
    assert (
        hr_feed.say("en", "Проверить сроки на витрине")
        == "Проверить сроки на витрине"
    )


def test_reason_suffix() -> None:
    suffix = hr_feed.say("en", " (причина: {reason})", reason="нет доступа")
    text = hr_feed.say(
        "en",
        "сообщил(а) о проблеме по «{title}»{suffix}",
        title="Залить воду",
        suffix=suffix,
    )
    assert text == "reported a problem with “Залить воду” (reason: нет доступа)"
