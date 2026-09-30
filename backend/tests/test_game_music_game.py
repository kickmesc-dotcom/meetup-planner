"""GHG10 Э16: мьюзик-гейм — чистая логика и жизненный цикл раунда.

БД-стенда нет: выбор вариантов, подписи и верный индекс — чистыми функциями;
открытие/закрытие раунда — с подменой выборки, `_names` и фасада начислений.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db.models import MusicGameRound, MusicTrack
from app.services.game import music_game
from app.services.game.config import (
    MUSIC_GAME_AUTHOR_REWARD,
    MUSIC_GAME_GUESS_REWARD,
    MUSIC_GAME_MAX_OPTIONS,
    MUSIC_GAME_MIN_OPTIONS,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Чистая логика
# --------------------------------------------------------------------------


def test_options_for_includes_author_and_caps():
    proposers = [1, 2, 3, 4, 5, 6, 7]
    options = music_game.options_for(4, proposers, rng=random.Random(0))
    assert 4 in options
    assert len(options) == MUSIC_GAME_MAX_OPTIONS
    assert len(set(options)) == len(options)


def test_options_for_needs_minimum_candidates():
    # Только автор — не из чего выбирать.
    assert music_game.options_for(1, [1], rng=random.Random(0)) == []
    # Автор и один отвлекающий — ровно минимум.
    two = music_game.options_for(1, [1, 2], rng=random.Random(0))
    assert sorted(two) == [1, 2]
    assert MUSIC_GAME_MIN_OPTIONS == 2


def test_correct_index():
    assert music_game.correct_index([3, 1, 2], 1) == 1
    assert music_game.correct_index([3, 1, 2], 9) is None


def test_dedupe_labels_makes_variants_unique():
    labels = music_game.dedupe_labels(["Митян", "Митян", "Сомов", "Митян"])
    assert labels == ["Митян", "Митян (2)", "Сомов", "Митян (3)"]
    assert len(set(labels)) == len(labels)


def test_texts_mention_author_and_reward():
    track = MusicTrack(user_id=1, kind="link", url="https://youtu.be/x", title="Крутая")
    assert "Крутая" in music_game.round_lead_text(track)
    assert "https://youtu.be/x" in music_game.round_lead_text(track)
    assert "Митян" in music_game.answer_text("Митян")
    assert str(MUSIC_GAME_GUESS_REWARD) in music_game.guesses_text(
        ["Сомов"], reward=MUSIC_GAME_GUESS_REWARD
    )
    assert "никто" in music_game.guesses_text([], reward=MUSIC_GAME_GUESS_REWARD)


# --------------------------------------------------------------------------
# register_guess
# --------------------------------------------------------------------------


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _round(*, option_user_ids=(10, 20, 30), correct=20, voters=None, closed=None):
    return MusicGameRound(
        id=7,
        chat_id=-100,
        track_id=5,
        correct_user_id=correct,
        option_user_ids=list(option_user_ids),
        correct_voter_ids=list(voters or []),
        closed_at=closed,
    )


@pytest.mark.asyncio
async def test_register_guess_records_correct_vote():
    row = _round()
    session = _Session()
    ok = await music_game.register_guess(
        session, round=row, user_id=99, option_index=1
    )
    assert ok is True
    assert row.correct_voter_ids == [99]
    assert session.commits == 1
    # Повтор того же голоса — не дублируется.
    again = await music_game.register_guess(
        session, round=row, user_id=99, option_index=1
    )
    assert again is False
    assert row.correct_voter_ids == [99]


@pytest.mark.asyncio
async def test_register_guess_ignores_wrong_option_and_closed():
    row = _round()
    session = _Session()
    assert (
        await music_game.register_guess(
            session, round=row, user_id=99, option_index=0
        )
        is False
    )
    assert row.correct_voter_ids == []

    closed = _round(closed=NOW)
    assert (
        await music_game.register_guess(
            _Session(), round=closed, user_id=99, option_index=1
        )
        is False
    )


# --------------------------------------------------------------------------
# open_round
# --------------------------------------------------------------------------


class _Bot:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.polls: list[list[str]] = []

    async def send_message(self, *, chat_id, text, parse_mode=None):  # noqa: ANN001
        self.messages.append(text)
        return SimpleNamespace(message_id=11)

    async def send_poll(self, *, chat_id, question, options, **kwargs):  # noqa: ANN001
        self.polls.append(list(options))
        return SimpleNamespace(poll=SimpleNamespace(id="poll-1"))

    async def send_audio(self, **_kwargs):  # noqa: ANN003
        raise AssertionError("в этом тесте аудио не отправляется")


class _SessionForOpen:
    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_open_round_happy_path(monkeypatch):
    track = MusicTrack(id=5, user_id=1, kind="link", url="https://x.y", title="Трек")
    monkeypatch.setattr(music_game, "proposer_ids", lambda _s: _async([1, 2, 3]))
    monkeypatch.setattr(music_game, "eligible_tracks", lambda _s: _async([track]))
    monkeypatch.setattr(
        music_game, "_names", lambda _s, ids: _async({1: "Митян", 2: "Сомов", 3: "Грек"})
    )
    monkeypatch.setattr(
        music_game,
        "get_settings",
        lambda: SimpleNamespace(group_chat_id=-100),
    )

    session = _SessionForOpen()
    bot = _Bot()
    row = await music_game.open_round(
        session, bot, now=NOW, rng=random.Random(0)
    )
    assert row is not None
    assert row.tg_poll_id == "poll-1"
    assert row.correct_user_id == 1
    assert row.option_user_ids and 1 in row.option_user_ids
    assert len(bot.polls) == 1
    # Автор есть среди вариантов — иначе угадать нечего.
    assert len(bot.polls[0]) == len(row.option_user_ids)
    assert session.added and session.added[0] is row


@pytest.mark.asyncio
async def test_open_round_without_candidates(monkeypatch):
    monkeypatch.setattr(music_game, "proposer_ids", lambda _s: _async([1]))
    monkeypatch.setattr(music_game, "eligible_tracks", lambda _s: _async([]))
    monkeypatch.setattr(
        music_game, "get_settings", lambda: SimpleNamespace(group_chat_id=-100)
    )
    assert (
        await music_game.open_round(
            _SessionForOpen(), _Bot(), now=NOW, rng=random.Random(0)
        )
        is None
    )


def _async(value):  # noqa: ANN001
    """Обернуть значение в awaitable (замена async-функций в monkeypatch)."""

    async def _inner(*_a, **_k):  # noqa: ANN002, ANN003
        return value

    return _inner()


# --------------------------------------------------------------------------
# finalize_round
# --------------------------------------------------------------------------


class _Awards:
    def __init__(self) -> None:
        self.authors: list[tuple[int, int]] = []
        self.guesses: list[tuple[int, int]] = []

    async def music_author(self, _s, uid, *, points, round_id=None, at=None):  # noqa: ANN001
        self.authors.append((uid, points))

    async def music_guess(self, _s, uid, *, points, round_id=None, at=None):  # noqa: ANN001
        self.guesses.append((uid, points))


class _Journal:
    KIND_EVENT = "event"

    def __init__(self) -> None:
        self.events: list[str] = []

    async def announce(self, _s, *, kind=None, subject_user_id=None, text=""):  # noqa: ANN001
        self.events.append(text)
        return True


@pytest.mark.asyncio
async def test_finalize_round_awards_author_and_guessers(monkeypatch):
    row = _round(voters=[7, 8])
    monkeypatch.setattr(
        music_game, "_names", lambda _s, ids: _async({20: "Автор", 7: "Аня", 8: "Боря"})
    )
    awards = _Awards()
    journal = _Journal()
    monkeypatch.setattr(music_game, "awards", awards)
    monkeypatch.setattr(music_game, "journal", journal)

    session = _Session()
    bot = _Bot()
    result = await music_game.finalize_round(
        session, bot, row, now=NOW, poll=SimpleNamespace()
    )
    assert result is not None
    assert result.author_id == 20
    assert result.guessed_ids == [7, 8]
    assert awards.authors == [(20, MUSIC_GAME_AUTHOR_REWARD)]
    assert awards.guesses == [
        (7, MUSIC_GAME_GUESS_REWARD),
        (8, MUSIC_GAME_GUESS_REWARD),
    ]
    assert row.closed_at == NOW
    assert row.outcome == music_game.OUTCOME_POLL
    # Повторный вызов — идемпотентно.
    assert await music_game.finalize_round(session, bot, row, now=NOW) is None
    assert len(awards.authors) == 1
    assert len(awards.guesses) == 2


@pytest.mark.asyncio
async def test_finalize_stale_rounds_closes_old(monkeypatch):
    old = _round()
    old.created_at = NOW - timedelta(hours=5)

    async def fake_finalize(_s, _b, row, *, now, poll=None):  # noqa: ANN001
        assert poll is None
        row.closed_at = now
        return music_game.RoundResult(row.id, row.correct_user_id, [])

    monkeypatch.setattr(music_game, "finalize_round", fake_finalize)

    class _Scalars:
        def all(self):  # noqa: ANN201
            return [old]

    class _S:
        async def scalars(self, *_a, **_k):  # noqa: ANN002, ANN003
            return _Scalars()

    closed = await music_game.finalize_stale_rounds(_S(), _Bot(), now=NOW)
    assert closed == 1
