"""GHG7 P5 / GHG8 F-media-fix: тесты детектора медиа-реакций (классификация +
in-memory store).

Без БД/сети: проверяем чистую классификацию альбома, store «последнего медиа»
для force-кнопок и одиночный ролл шанса (roll_chance) с детерминированным
random.Random(seed). Async-БД-стенда в проекте нет — здесь только pure-логика
handler'а (как в test_media_reactions.py).
"""
from __future__ import annotations

import random

import pytest

from app.bot.handlers import media_reactions as mr
from app.services.media_reactions import roll_chance


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


def test_single_roll_fires_at_full_chance():
    """Шанс 100% → одиночный ролл всегда срабатывает (детерминированно)."""
    rng = random.Random(0)
    assert roll_chance(100, rng) is True


def test_single_roll_never_fires_at_zero_chance():
    """Шанс 0% → бот не реагирует никогда (это и есть честная семантика)."""
    rng = random.Random(0)
    assert roll_chance(0, rng) is False


def test_single_roll_respects_probability():
    """Один ролл на мем: при шансе X% доля срабатываний ≈ X% (без накопления
    серии, которая раньше копила ~98% из «10–50%»)."""
    rng = random.Random(12345)
    pct = 30
    hits = sum(roll_chance(pct, rng) for _ in range(10000))
    # Допуск ±3 п.п. от 30% — гард, что ролл одиночный и честный.
    assert 0.27 <= hits / 10000 <= 0.33
