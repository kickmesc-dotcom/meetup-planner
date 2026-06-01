"""GHG7 P9.5.b: header-маппинг compose_loser_message для разделённой семантики
«Лох дня» (👑) vs «Автолох-дуэль» (🤡).

Маппинг (контракт P9):
  - auto (scheduler) / manual (admin force-reroll) → 👑 «Лох дня» (в статистику).
  - duel (/loser + LoserSheet)                     → 🤡 «Автолох» (НЕ в статистику).

compose_loser_message сам по себе не знает про source — caller передаёт
header_emoji/header_label. Тест фиксирует, что функция корректно вставляет их в
шапку, чтобы рассинхрон caller'ов ловился (а не молча инвертировался, как было
до P9).
"""
from __future__ import annotations

from app.services.loser import compose_loser_message


def test_header_loser_dnya_crown():
    """auto/manual → 👑 «Лох дня»."""
    out = compose_loser_message(
        loser_name="Митя",
        reason_text="проспал",
        header_emoji="👑",
        header_label="Лох дня",
    )
    assert out.startswith("👑 <b>Лох дня</b> — Митя!")
    assert "🤡" not in out


def test_header_avtoloh_clown():
    """duel → 🤡 «Автолох» + кто покрутил, без счётчика статистики."""
    out = compose_loser_message(
        loser_name="Сомов",
        reason_text="сам напросился",
        roller_name="Никита",
        loser_count=None,  # duel не идёт в статистику → счётчик не печатаем
        header_emoji="🤡",
        header_label="Автолох",
    )
    assert out.startswith("🤡 <b>Автолох</b> — Сомов!")
    assert "Покрутил рулетку: Никита" in out
    assert "👑" not in out
    # P9.1.b: loser_count=None → строки про «N-й раз лохом» нет.
    assert "становится лохом" not in out


def test_header_loser_count_printed_when_set():
    """Контроль: при заданном loser_count счётчик печатается (auto/manual путь)."""
    out = compose_loser_message(
        loser_name="Кравченко",
        reason_text="опять",
        loser_count=4,
        header_emoji="👑",
        header_label="Лох дня",
    )
    assert "4-й раз становится лохом" in out
