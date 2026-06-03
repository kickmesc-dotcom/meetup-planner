"""GHG7 P5: тесты детектора медиа-реакций (классификация + in-memory store).

Без БД/сети: проверяем чистую классификацию альбома, store «последнего медиа»
для force-кнопок и интеграцию шанса по тикам (tick_chance+roll_chance) с
детерминированным random.Random(seed). Async-БД-стенда в проекте нет — здесь
только pure-логика handler'а (как в test_media_reactions.py).
"""
from __future__ import annotations

import random

import pytest

from app.bot.handlers import media_reactions as mr
from app.services.media_reactions import WAIT_TICKS_MIN, roll_chance, tick_chance


def test_classify_album_single_vs_collection():
    assert mr.classify_album(1) == "single"
    assert mr.classify_album(2) == "collection"
    assert mr.classify_album(5) == "collection"
    # 0 теоретически невозможно (буфер создаётся с count=1), но не падаем.
    assert mr.classify_album(0) == "single"


@pytest.fixture(autouse=True)
def _clear_recent():
    """Изолируем глобальный store между тестами."""
    mr._recent.clear()
    mr._reacted.clear()
    yield
    mr._recent.clear()
    mr._reacted.clear()


def test_get_recent_empty_returns_none():
    assert mr.get_recent(123, "single") is None
    assert mr.get_recent(123, "collection") is None


def test_get_recent_kind_must_match():
    mr._recent[42] = ("single", 999, "Митян")
    assert mr.get_recent(42, "single") == (999, "Митян")
    # Запрошен другой тип — не отдаём чужое.
    assert mr.get_recent(42, "collection") is None


def test_get_recent_other_chat_isolated():
    mr._recent[42] = ("collection", 7, "Дрон")
    assert mr.get_recent(99, "collection") is None
    assert mr.get_recent(42, "collection") == (7, "Дрон")


def test_recent_overwrite_keeps_latest():
    mr._recent[1] = ("single", 10, "A")
    mr._recent[1] = ("collection", 20, "B")
    assert mr.get_recent(1, "single") is None
    assert mr.get_recent(1, "collection") == (20, "B")


def test_tick_chance_series_is_monotonic_and_bounded():
    """Серия шансов по реальным тикам растёт от base к max и зажата в [0,100]."""
    n = len(WAIT_TICKS_MIN)
    series = [tick_chance(i, 10, 50, n) for i in range(n)]
    assert series[0] == 10
    assert series[-1] == 50
    assert series == sorted(series)
    assert all(0 <= p <= 100 for p in series)


def test_reaction_fires_eventually_at_high_chance():
    """С высоким шансом (always-like 100/100) первый же ролл срабатывает."""
    rng = random.Random(0)
    # base=max=100 → tick_chance==100 на любом тике → roll_chance True.
    assert tick_chance(0, 100, 100, len(WAIT_TICKS_MIN)) == 100
    assert roll_chance(100, rng) is True


def test_reaction_never_fires_at_zero_chance():
    rng = random.Random(0)
    assert tick_chance(0, 0, 0, len(WAIT_TICKS_MIN)) == 0
    assert roll_chance(0, rng) is False
