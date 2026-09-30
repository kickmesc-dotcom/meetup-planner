"""GHG10 Э9: пожизненные иммунитеты за ранги 9 (лох) и 10 (чухан).

Async-БД-стенда в проекте нет (зафиксированное ограничение), поэтому:

- чистая часть (`immunity_level`, `immunity_threshold_xp`, `immunity_reason`) —
  напрямую;
- `rank_immune_reasons` — через фейковую сессию и подменённый рубильник: запрос
  к БД тут не проверяем, проверяем решение (кого считать иммунным и что сказать
  чату) и то, что выключенный рубильник гасит иммунитеты раньше любого запроса;
- оглашение — через `resolve_immune_pick` из `birthday_immunity` (единственная
  точка броска с учётом иммунитета, Э9 встроена в неё, а не в свою копию).
"""
from __future__ import annotations

import pytest

from app.services.birthday_immunity import resolve_immune_pick
from app.services.game import levels
from app.services.game.immunity import (
    immunity_level,
    immunity_reason,
    immunity_threshold_xp,
    rank_immune_reasons,
)
from app.services.immunity import BIRTHDAY, CHUKHAN_IMMUNITY, LOSER_IMMUNITY


class _U:
    """Двойник User: resolve_immune_pick трогает только id/display_name."""

    def __init__(self, uid: int, name: str | None = None):
        self.id = uid
        self.display_name = name or f"user{uid}"


USERS = [_U(1, "Митя"), _U(2, "Никита"), _U(3, "Серёга")]


def _seq_pick(sequence):
    """Детерминированная стратегия: выдаёт юзеров с заданными id по очереди."""
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


# --- пороги берутся из конфига, а не из кода -------------------------------------------------

def test_levels_come_from_config_unlocks():
    assert immunity_level("loser") == 9
    assert immunity_level("chukhan") == 10


# Пороги 9/10 уровней берём из шкалы (прогрессивная: 3600 / 4500 при шаге 100).
L9 = levels.xp_for_level(9)
L10 = levels.xp_for_level(10)


def test_threshold_matches_calculated_level():
    assert immunity_threshold_xp("loser") == L9
    assert immunity_threshold_xp("chukhan") == L10
    for kind, threshold in (("loser", L9), ("chukhan", L10)):
        assert levels.level_for_xp(threshold) == immunity_level(kind)
        # На один XP меньше — уровень уже ниже порога (граница ровно на пороге).
        assert levels.level_for_xp(threshold - 1) < immunity_level(kind)


# --- тексты оглашений --------------------------------------------------------

def test_loser_reason_text_names_rank_and_immunity():
    text = immunity_reason(9, "loser").text("Митя")
    assert "<b>Митя</b>" in text
    assert "9-й ранг" in text
    assert levels.rank_for_level(9).name in text
    assert "иммунитет к лоху навсегда" in text


def test_chukhan_reason_text_names_rank_and_immunity():
    text = immunity_reason(10, "chukhan").text("Серёга")
    assert "<b>Серёга</b>" in text
    assert "10-й ранг" in text
    assert levels.rank_for_level(10).name in text
    assert "иммунитет к чухану навсегда" in text


def test_reason_codes_match_immunity_kinds():
    assert immunity_reason(9, "loser").code == LOSER_IMMUNITY
    assert immunity_reason(10, "chukhan").code == CHUKHAN_IMMUNITY


# --- решение: кого считать иммунным -----------------------------------------

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Сессия-заглушка: `execute` отдаёт заранее заданные строки (id, xp)."""

    def __init__(self, rows):
        self.rows = rows

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self.rows)


@pytest.fixture
def game_on(monkeypatch):
    async def _on(_session):
        return True

    monkeypatch.setattr("app.services.game.immunity.is_game_enabled", _on)


@pytest.mark.asyncio
async def test_rank_immunity_empty_when_game_disabled(monkeypatch):
    calls: list[str] = []

    async def _off(_session):
        calls.append("checked")
        return False

    class _NoQuery:
        async def execute(self, *_a, **_k):  # pragma: no cover — не должен зваться
            raise AssertionError("SQL не должен выполняться при выключенной игре")

    monkeypatch.setattr("app.services.game.immunity.is_game_enabled", _off)
    assert await rank_immune_reasons(_NoQuery(), kind="loser") == {}
    assert calls == ["checked"]


@pytest.mark.asyncio
async def test_loser_immunity_starts_at_level_nine(game_on):
    session = _FakeSession([(1, L9), (2, L9 - 1), (3, L10)])
    reasons = await rank_immune_reasons(session, kind="loser")
    # Порог 9 уровня → иммунен, на 1 XP меньше → 8 (нет), 10 уровень → тоже иммунен.
    assert set(reasons) == {1, 3}
    assert reasons[1].code == LOSER_IMMUNITY
    assert "9-й ранг" in reasons[1].template
    assert "10-й ранг" in reasons[3].template


@pytest.mark.asyncio
async def test_chukhan_immunity_needs_level_ten(game_on):
    session = _FakeSession([(1, L9), (3, L10)])
    reasons = await rank_immune_reasons(session, kind="chukhan")
    # Девятого ранга для иммунитета к чухану мало.
    assert set(reasons) == {3}
    assert reasons[3].code == CHUKHAN_IMMUNITY


@pytest.mark.asyncio
async def test_immune_reason_is_per_user(game_on):
    session = _FakeSession([(1, L9), (3, L10)])
    reasons = await rank_immune_reasons(session, kind="chukhan")
    text = reasons[3].text("Серёга")
    assert "Серёга" in text
    assert "Митя" not in text


# --- встраивание в общий бросок с иммунитетом --------------------------------

def test_announce_uses_rank_reason_text():
    res = resolve_immune_pick(
        USERS,
        {1},
        "announce",
        _seq_pick([1, 3]),
        reasons={1: immunity_reason(9, "loser")},
    )
    assert res.user is USERS[2]
    assert res.skipped_names == ["Митя"]  # совместимость со старым API
    assert res.skipped[0].reason.code == LOSER_IMMUNITY
    assert "9-й ранг" in res.skipped[0].text


def test_announce_without_reason_falls_back_to_birthday():
    # Историческое поведение GHG8 не меняется: без причины в reasons — ДР.
    res = resolve_immune_pick(USERS, {1}, "announce", _seq_pick([1, 3]))
    assert res.skipped_names == ["Митя"]
    assert res.skipped[0].reason.code == BIRTHDAY
    assert "день рождения" in res.skipped[0].text


def test_announce_mixed_reasons_are_not_confused():
    # У двух иммунных — разные причины; в skipped попадает та, чей id выпал.
    res = resolve_immune_pick(
        USERS,
        {1, 2},
        "announce",
        _seq_pick([2, 3]),
        reasons={1: immunity_reason(9, "loser"), 2: immunity_reason(10, "chukhan")},
    )
    assert res.skipped_names == ["Никита"]
    assert res.skipped[0].reason.code == CHUKHAN_IMMUNITY


def test_silent_excludes_rank_immune_from_pool():
    seen = []

    def pick(pool):
        seen.append([u.id for u in pool])
        return pool[0]

    res = resolve_immune_pick(
        USERS, {1}, "silent", pick, reasons={1: immunity_reason(9, "loser")}
    )
    assert seen == [[2, 3]]
    assert res.user is USERS[1]
    assert res.skipped == []


def test_all_immune_still_returns_someone():
    # Вырожденный кейс «иммунны все»: иммунитет игнорируется, ролл не падает.
    res = resolve_immune_pick(
        USERS,
        {1, 2, 3},
        "announce",
        lambda pool: pool[-1],
        reasons={u.id: immunity_reason(9, "loser") for u in USERS},
    )
    assert res.user is USERS[-1]
    assert res.skipped == []
