"""Чистые правила KPI-геймификации: опыт, звания, номинация недели.

Тесты без БД намеренно: это арифметика, которую админ меняет из мини-аппа.
Если правило сломается, оно сломается здесь — а не «в бою на закрытии смены».
"""

from __future__ import annotations

from datetime import date

from app.services.hr_kpi import (
    DEFAULT_RULES,
    RANKS,
    Candidate,
    Counts,
    Rules,
    clamp_min_xp,
    clamp_weight,
    next_rank_for,
    pick_winner,
    progress_for,
    rank_for,
    week_bounds,
    xp_for,
)


def _counts(items: int = 0, shifts: int = 0, tasks: int = 0, on_time: int = 0) -> Counts:
    return Counts(
        checklist_items=items,
        shifts_done=shifts,
        tasks_done=tasks,
        tasks_on_time=on_time,
    )


def test_xp_sums_each_trace_of_work() -> None:
    """Опыт = сумма весов; ни одна метрика не «теряется»."""
    assert xp_for(_counts()) == 0
    assert xp_for(_counts(items=10, shifts=1, tasks=2, on_time=1)) == (
        10 * 2 + 1 * 10 + 2 * 15 + 1 * 5
    )


def test_admin_weights_change_xp() -> None:
    """Веса из админки реально влияют на начисление, а не только на подпись."""
    rules = Rules(xp_checklist_item=0, xp_shift_done=5, xp_task=50, xp_on_time=0)
    assert xp_for(_counts(items=100, shifts=1, tasks=1, on_time=1), rules) == 55


def test_rank_ladder_is_monotonic_and_neutral() -> None:
    """Звание растёт по опыту и не содержит шуточных ярлыков."""
    assert rank_for(0).title == "Стажёр"
    assert rank_for(99).title == "Стажёр"
    assert rank_for(100).title == "В смене"
    assert rank_for(10_000).title == "Мастер смены"
    forbidden = {"лох", "чухан", "червь"}
    for rank in RANKS:
        assert not any(word in rank.title.lower() for word in forbidden)


def test_next_rank_and_progress_percent() -> None:
    """Прогресс до следующего звания: остаток и процент считаются от порога."""
    assert next_rank_for(0) is not None
    assert next_rank_for(10_000) is None
    step = progress_for(200)  # между «В смене» (100) и «Ровный ход» (300)
    assert step.left == 100
    assert step.percent == 50
    top = progress_for(5000)
    assert top.next_rank is None and top.percent == 100


def test_week_bounds_is_monday_to_sunday() -> None:
    """Неделя ресторана — календарная пн–вс, включая воскресенье."""
    monday, sunday = week_bounds(date(2026, 10, 17))  # суббота
    assert (monday, sunday) == (date(2026, 10, 12), date(2026, 10, 18))


def test_winner_respects_minimum_and_ignores_demo_pool() -> None:
    """Номинация: минимум опыта, живые люди, тай-брейк по поручениям."""
    low = Candidate(1, "Мало", None, _counts(items=1), xp=2)
    demo = Candidate(2, "[BOT] Симулятор", None, _counts(tasks=50), xp=999, is_demo=True)
    strong = Candidate(3, "Сильная смена", "Кухня", _counts(tasks=4), xp=80)
    also = Candidate(4, "Ровно столько же", "Бар", _counts(tasks=1), xp=80)

    assert pick_winner([low, demo], DEFAULT_RULES) is None
    winner = pick_winner([low, demo, strong, also], DEFAULT_RULES)
    assert winner is not None
    assert winner.employee_id == 3  # при равном опыте — больше поручений
    assert winner.department == "Кухня"


def test_clamps_keep_weights_sane() -> None:
    """Отрицательный вес или «миллион» из админки не ломают баланс."""
    assert clamp_weight(-10) == 0
    assert clamp_weight(10_000) == 100
    assert clamp_min_xp(-1) == 0
    assert clamp_min_xp(10_000) == 1000
