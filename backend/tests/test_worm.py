"""GHG6 E8 — «Червь-пидор»: чистая логика broska/композиции сообщения.

Интеграция с БД (создание `WormAssignment`, закрытие предыдущего, partial
unique index) проверяется руками при первом ролле — отдельный sqlite-стенд
в проект не тащим (его нет для других сервисов). Здесь — только декомпозируемая
часть: `decide_worm` и `compose_loser_message`.
"""
from __future__ import annotations

from app.services.loser import (
    RollExtras,
    WormEvent,
    WORM_REASON_TEXT,
    compose_loser_message,
    decide_worm,
)


# ----- decide_worm -----

def test_decide_worm_disabled_never_triggers():
    assert decide_worm(enabled=False, chance=1.0, rng_value=0.0) is False
    assert decide_worm(enabled=False, chance=0.5, rng_value=0.4) is False


def test_decide_worm_zero_chance_never_triggers():
    assert decide_worm(enabled=True, chance=0.0, rng_value=0.0) is False


def test_decide_worm_boundary_rng_below_chance_triggers():
    # rng_value < chance → True
    assert decide_worm(enabled=True, chance=0.01, rng_value=0.009) is True


def test_decide_worm_boundary_rng_equal_chance_does_not_trigger():
    # rng_value == chance → False (строгое <)
    assert decide_worm(enabled=True, chance=0.01, rng_value=0.01) is False


def test_decide_worm_full_chance_always_triggers():
    # При chance=1.0 любое rng_value < 1.0 → True
    assert decide_worm(enabled=True, chance=1.0, rng_value=0.99) is True


# ----- compose_loser_message -----

def test_compose_regular_loser_no_extras():
    out = compose_loser_message(
        loser_name="Серёжа Neo",
        reason_text="воюет не в ту сторону",
        roller_name="Никита",
        loser_count=3,
    )
    assert "Серёжа Neo" in out
    assert "воюет не в ту сторону" in out
    assert "3-й раз" in out
    assert "Никита" in out
    assert "🪱" not in out
    assert "ЧЕРВЬ" not in out


def test_compose_worm_message_replaces_layout():
    out = compose_loser_message(
        loser_name="Дмитрий-JDM",
        reason_text=WORM_REASON_TEXT,
        roller_name="Никита",
        loser_count=5,
        extras=RollExtras(worm=WormEvent(triggered=True)),
    )
    assert "ОСОБАЯ НОМИНАЦИЯ" in out
    assert "🪱" in out
    assert "Дмитрий-JDM" in out
    # Обычные слова шаблона лоха («Причина:») не должны попадать в worm-сообщение
    assert "Причина:" not in out


def test_compose_worm_with_previous_holder_mentions_transfer():
    out = compose_loser_message(
        loser_name="Никита",
        reason_text=WORM_REASON_TEXT,
        extras=RollExtras(worm=WormEvent(triggered=True, prev_worm_name="Русланище")),
    )
    assert "Русланище" in out
    assert "слагает полномочия" in out


def test_compose_worm_without_previous_holder_no_transfer_line():
    out = compose_loser_message(
        loser_name="Никита",
        reason_text=WORM_REASON_TEXT,
        extras=RollExtras(worm=WormEvent(triggered=True, prev_worm_name=None)),
    )
    assert "слагает полномочия" not in out


def test_compose_worm_same_user_repeat_no_self_transfer_line():
    # Если предыдущий червь — тот же юзер (повторное выпадение), линии
    # «слагает полномочия» быть не должно.
    out = compose_loser_message(
        loser_name="Никита",
        reason_text=WORM_REASON_TEXT,
        extras=RollExtras(worm=WormEvent(triggered=True, prev_worm_name="Никита")),
    )
    assert "слагает полномочия" not in out
