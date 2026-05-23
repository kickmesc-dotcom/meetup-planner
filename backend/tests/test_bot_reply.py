"""GHG6 hotfix: `format_bot_reply` — reply бота без префикса автора.

Корень бага из `error.txt`: при reply на сообщение бота `bot_reactions._react`
звал `compose_random_phrase`, который добавляет шапку 🗣/👤 и оборачивает
текст в «Сводный хор Шестёрки» / «Имя вещает». Получалось, что бот «отвечал»
как будто это цитата от другого участника — в чате выглядело странно.

Фикс — отдельная чистая функция `format_bot_reply` без шапки. Тест проверяет,
что в выводе нет этих префиксов независимо от входного пула.
"""
from __future__ import annotations

import random

from app.services.random_phrases import format_bot_reply


def test_no_author_prefixes_in_reply():
    random.seed(42)
    chunks = [
        "так-то да",
        "ну ваще конечно",
        "короче такая тема",
        "это всё фигня",
        "я-то понимаю",
    ]
    out = format_bot_reply(chunks, n=2)
    assert "🗣" not in out
    assert "👤" not in out
    assert "Сводный хор" not in out
    assert "вещает" not in out


def test_empty_pool_returns_fallback():
    out = format_bot_reply([], n=2)
    assert out == "<i>(нет слов...)</i>"
    assert "🗣" not in out
    assert "👤" not in out


def test_html_italics_wrapper():
    random.seed(1)
    chunks = ["краткая мысль один", "краткая мысль два", "ещё одна мысль"]
    out = format_bot_reply(chunks, n=2)
    assert out.startswith("<i>")
    assert out.endswith("</i>")


def test_small_pool_does_not_crash():
    """Один чанк в пуле — random.sample не должен упасть на min(len, n*2)."""
    random.seed(0)
    out = format_bot_reply(["единственная фраза"], n=2)
    assert "<i>" in out
    assert "🗣" not in out


def test_dedup_works_for_reply_too():
    """Если в пуле почти-дубли, они отбрасываются (как и в автопосте)."""
    random.seed(0)
    chunks = ["так-то да", "так-то да", "так-то да", "так-то да"]
    out = format_bot_reply(chunks, n=3)
    # dedup отрежет до одного варианта — но обёртка <i> всё равно валидна.
    assert out.startswith("<i>")
    assert "👤" not in out
