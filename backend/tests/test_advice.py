"""GHG8 T3.4: тесты чистого ядра «магического шара» (без БД/aiogram).

Покрывает pick_advice (честный рандом + пустой пул), text_has_advice_hashtag
(#совет/#advice, регистр, граница слова), ends_with_question (хвостовые
пробелы, множественные «?»).
"""
from __future__ import annotations

import random

from app.services.advice import (
    DEFAULT_ADVICE_PHRASES,
    ends_with_question,
    pick_advice,
    text_has_advice_hashtag,
)


def test_pick_advice_returns_member():
    pool = ["Да.", "Нет.", "Возможно."]
    rng = random.Random(42)
    for _ in range(20):
        # детерминизм не критичен — проверяем только принадлежность пулу
        assert pick_advice(pool) in pool
    _ = rng


def test_pick_advice_empty_pool_is_none():
    assert pick_advice([]) is None
    assert pick_advice(None) is None
    # пул из пустых/пробельных строк = фактически пуст
    assert pick_advice(["", "  ", "\t"]) is None


def test_pick_advice_skips_blank_entries():
    assert pick_advice(["", "  ", "Точно да."]) == "Точно да."


def test_default_pool_nonempty_and_strings():
    assert len(DEFAULT_ADVICE_PHRASES) >= 10
    assert all(isinstance(p, str) and p.strip() for p in DEFAULT_ADVICE_PHRASES)


def test_hashtag_detects_both_languages():
    assert text_has_advice_hashtag("дай #совет пожалуйста")
    assert text_has_advice_hashtag("need #advice now")
    assert text_has_advice_hashtag("#совет")
    assert text_has_advice_hashtag("в начале строки\n#advice")


def test_hashtag_case_insensitive():
    assert text_has_advice_hashtag("#Совет")
    assert text_has_advice_hashtag("#ADVICE")


def test_hashtag_negatives():
    assert not text_has_advice_hashtag(None)
    assert not text_has_advice_hashtag("")
    assert not text_has_advice_hashtag("просто текст без хештега")
    # без решётки — не триггер
    assert not text_has_advice_hashtag("дай совет")
    # склейка с другим словом — не отдельный хештег-токен
    assert not text_has_advice_hashtag("#советский")
    assert not text_has_advice_hashtag("#adviced")


def test_ends_with_question():
    assert ends_with_question("а не пора ли встретиться?")
    assert ends_with_question("точно?   ")  # хвостовые пробелы триммятся
    assert ends_with_question("ну что???")
    assert not ends_with_question("это утверждение.")
    assert not ends_with_question("вопрос? но потом ещё текст")
    assert not ends_with_question(None)
    assert not ends_with_question("")
