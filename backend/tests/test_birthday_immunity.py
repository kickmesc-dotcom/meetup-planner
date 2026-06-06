"""GHG8 P3: иммунитет именинника к лоху/чухану.

Async-БД-стенда нет (зафиксированное ограничение) — кроем чистую логику:
`resolve_immune_pick` (оба режима, вырожденные пулы, «2 именинника в день»)
и `format_immunity_announce`. I/O-обёртки (`immune_pick`,
`birthday_user_ids_today`) — тонкие, без своей логики.
"""
from __future__ import annotations

import pytest

from app.services.birthday_immunity import (
    MAX_ANNOUNCE_REROLLS,
    format_immunity_announce,
    resolve_immune_pick,
)


class _U:
    """Лёгкий двойник User — resolve_immune_pick трогает только id/display_name."""

    def __init__(self, uid: int, name: str | None = None):
        self.id = uid
        self.display_name = name or f"user{uid}"

    def __repr__(self) -> str:  # удобнее читать падения
        return f"_U({self.id})"


def _seq_pick(sequence):
    """Детерминированная стратегия: выдаёт юзеров с заданными id по очереди,
    но только если они есть в текущем пуле (иначе — первый из пула)."""
    it = iter(sequence)

    def pick(pool):
        try:
            want = next(it)
        except StopIteration:
            return pool[0]
        for u in pool:
            if u.id == want:
                return u
        return pool[0]

    return pick


USERS = [_U(1, "Митя"), _U(2, "Никита"), _U(3, "Серёга")]


# --- пустой / вырожденный пул ---

def test_empty_pool_raises():
    with pytest.raises(RuntimeError):
        resolve_immune_pick([], set(), "silent", lambda pool: pool[0])


@pytest.mark.parametrize("mode", ["silent", "announce"])
def test_all_immune_falls_back_to_full_pool(mode):
    # Все — именинники: иммунитет невозможен, выбираем по полному пулу,
    # оглашений нет (нечего рероллить).
    res = resolve_immune_pick(USERS, {1, 2, 3}, mode, lambda pool: pool[-1])
    assert res.user is USERS[-1]
    assert res.skipped_names == []


# --- silent ---

def test_silent_excludes_immune_before_pick():
    seen_pools = []

    def pick(pool):
        seen_pools.append(list(pool))
        return pool[0]

    res = resolve_immune_pick(USERS, {1}, "silent", pick)
    # Именинник (id=1) не попал в пул вообще.
    assert seen_pools == [[USERS[1], USERS[2]]]
    assert res.user is USERS[1]
    assert res.skipped_names == []


def test_silent_no_immune_keeps_full_pool():
    res = resolve_immune_pick(USERS, set(), "silent", lambda pool: pool[0])
    assert res.user is USERS[0]
    assert res.skipped_names == []


# --- announce ---

def test_announce_non_immune_first_try_no_skips():
    res = resolve_immune_pick(USERS, {1}, "announce", _seq_pick([2]))
    assert res.user is USERS[1]
    assert res.skipped_names == []


def test_announce_immune_then_reroll():
    # Первый бросок — именинник (id=1), реролл по чистому пулу → id=3.
    res = resolve_immune_pick(USERS, {1}, "announce", _seq_pick([1, 3]))
    assert res.user is USERS[2]
    assert res.skipped_names == ["Митя"]


def test_announce_two_birthdays_same_day():
    # Граничный кейс «2 именинника в день»: первый бросок по полному пулу
    # может выдать именинника, но реролл идёт по пулу БЕЗ обоих — второе имя
    # в skipped появиться не может.
    res = resolve_immune_pick(USERS, {1, 2}, "announce", _seq_pick([2, 3]))
    assert res.user is USERS[2]
    assert res.skipped_names == ["Никита"]


def test_announce_skips_at_most_one_name():
    # Реролл всегда по non_immune ⇒ больше одного оглашения по построению
    # не бывает, даже если стратегия «настаивает» на именинниках.
    res = resolve_immune_pick(USERS, {1, 2}, "announce", _seq_pick([1, 3]))
    assert res.user is USERS[2]
    assert res.skipped_names == ["Митя"]
    assert len(res.skipped_names) <= MAX_ANNOUNCE_REROLLS


def test_announce_final_user_never_immune():
    # Свойство-инвариант: при наличии не-именинников финальный кандидат
    # никогда не именинник (любая адекватная стратегия).
    import random

    rng = random.Random(42)
    for _ in range(200):
        immune = {rng.choice([1, 2, 3])}
        res = resolve_immune_pick(USERS, immune, "announce", rng.choice)
        assert res.user.id not in immune


def test_announce_unknown_mode_treated_as_announce():
    # resolve_immune_pick ветвится только на 'silent' — любой другой режим
    # идёт по announce-пути (get_birthdays_immunity_mode и так нормализует).
    res = resolve_immune_pick(USERS, {1}, "garbage", _seq_pick([1, 2]))
    assert res.user is USERS[1]
    assert res.skipped_names == ["Митя"]


# --- format_immunity_announce ---

def test_format_announce_contains_name_and_birthday():
    text = format_immunity_announce("Митя")
    assert "<b>Митя</b>" in text
    assert "день" in text and "рождения" in text
    assert "иммунитет" in text.lower()
