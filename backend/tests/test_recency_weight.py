"""GHG8 P13: карантин свежести при выборе рандом-фраз.

Жалоба 05.06: бот «передразнивает» — цитата в большинстве случаев собрана из
3-5 последних сообщений чата. Фикс: выбор чанков взвешен по возрасту сообщения
(«порог + плато», `_recency_weight`): младше quarantine_hours → вес
quarantine_weight (≈0.05), старше → 1.0. Считается в Python на уже-извлечённом
пуле (sent_at уже в ChatMessage) — ноль доп. нагрузки на Neon.

Тестируем чистые функции `_recency_weight` / `_weighted_sample` +
статистическое свойство: свежие чанки выбираются на порядок реже старых.
"""
from __future__ import annotations

import random

from app.services.random_phrases import (
    RECENCY_QUARANTINE_HOURS_DEFAULT,
    RECENCY_QUARANTINE_WEIGHT_DEFAULT,
    _recency_weight,
    _weighted_sample,
    format_bot_reply,
)


# --- _recency_weight: порог + плато ------------------------------------------


def test_fresh_message_gets_quarantine_weight() -> None:
    assert _recency_weight(0.0) == RECENCY_QUARANTINE_WEIGHT_DEFAULT
    assert _recency_weight(17.9) == RECENCY_QUARANTINE_WEIGHT_DEFAULT


def test_old_message_gets_full_weight() -> None:
    assert _recency_weight(18.0) == 1.0  # ровно на пороге — уже «отстоялось»
    assert _recency_weight(48.0) == 1.0
    assert _recency_weight(168.0) == 1.0


def test_plateau_old_messages_are_equal() -> None:
    # Плато: 1 день и 6 дней — одинаковый вес (старые равны между собой).
    assert _recency_weight(24.0) == _recency_weight(144.0) == 1.0


def test_custom_threshold_and_weight() -> None:
    assert _recency_weight(5.0, quarantine_hours=6.0, quarantine_weight=0.2) == 0.2
    assert _recency_weight(6.0, quarantine_hours=6.0, quarantine_weight=0.2) == 1.0


def test_zero_quarantine_disables_filtering() -> None:
    # quarantine_hours=0 → ни одно сообщение не «свежее», все веса 1.0.
    assert _recency_weight(0.0, quarantine_hours=0.0) == 1.0


def test_negative_age_treated_as_fresh() -> None:
    # Часы рассинхрона могут дать слегка отрицательный возраст — это «свежее».
    assert _recency_weight(-0.5) == RECENCY_QUARANTINE_WEIGHT_DEFAULT


# --- _weighted_sample: взвешенный выбор из пула (text, age_hours) ------------


def test_weighted_sample_empty_pool() -> None:
    assert _weighted_sample([], 3) == []
    assert _weighted_sample([("a", 48.0)], 0) == []


def test_weighted_sample_returns_k_items() -> None:
    pool = [("старое", 48.0), ("свежее", 1.0)]
    random.seed(0)
    out = _weighted_sample(pool, 6)
    assert len(out) == 6
    assert set(out) <= {"старое", "свежее"}


def test_weighted_sample_prefers_old_chunks() -> None:
    """Статистика: старый чанк выбирается на порядок чаще свежего
    (вес 1.0 vs 0.05 → ожидание ~95% старых)."""
    pool = [("старое", 48.0), ("свежее", 1.0)]
    random.seed(42)
    picks = _weighted_sample(pool, 1000)
    old_share = picks.count("старое") / len(picks)
    assert old_share > 0.85, f"старых только {old_share:.0%}, ожидали >85%"


def test_weighted_sample_all_fresh_falls_back_evenly() -> None:
    """Весь пул свежий → все веса равны (quarantine_weight) → выбор фактически
    равновесный, пустоту не отдаём."""
    pool = [("a", 0.5), ("b", 1.0), ("c", 2.0)]
    random.seed(1)
    out = _weighted_sample(pool, 9)
    assert len(out) == 9
    assert set(out) <= {"a", "b", "c"}


def test_weighted_sample_zero_total_weight_fallback() -> None:
    """quarantine_weight=0 и полностью свежий пул → суммарный вес 0 →
    равновесный фолбэк вместо ValueError у random.choices."""
    pool = [("a", 0.5), ("b", 1.0)]
    random.seed(2)
    out = _weighted_sample(pool, 4, quarantine_weight=0.0)
    assert len(out) == 4
    assert set(out) <= {"a", "b"}


# --- format_bot_reply: aged_chunks применяет карантин -------------------------


def test_format_bot_reply_without_aged_chunks_unchanged() -> None:
    # Обратная совместимость: без aged_chunks — прежний равновесный путь.
    random.seed(0)
    out = format_bot_reply(["первая длинная фраза", "вторая длинная фраза"], n=2)
    assert out.startswith("<i>") and out.endswith("</i>")


def test_format_bot_reply_with_aged_chunks_skews_old() -> None:
    """С aged_chunks свежий чанк почти не попадает в reply (вес 0.05 vs 1.0).
    Прогоняем 50 раз с n=1: доля reply, содержащих старый чанк, должна
    доминировать."""
    chunks = ["старая отстоявшаяся фраза", "свежак из последнего сообщения"]
    aged = [("старая отстоявшаяся фраза", 48.0), ("свежак из последнего сообщения", 0.5)]
    old_hits = 0
    for seed in range(50):
        random.seed(seed)
        out = format_bot_reply(chunks, n=1, aged_chunks=aged)
        # lower(): _glue_chunks капитализирует первую букву («старая» → «Старая»).
        if "старая" in out.lower():
            old_hits += 1
    assert old_hits > 35, f"старый чанк только в {old_hits}/50 reply, ожидали >35"


def test_default_constants_sane() -> None:
    # Контракт дефолтов: 18ч карантин, вес 5% — то, что согласовано в P13.
    assert RECENCY_QUARANTINE_HOURS_DEFAULT == 18.0
    assert RECENCY_QUARANTINE_WEIGHT_DEFAULT == 0.05
