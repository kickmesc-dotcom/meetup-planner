"""GHG10 Э7: телеметрия мемов (мемолог / успешный успех / forever alone / опиум).

Async-БД-стенда нет — как и в остальных игровых тестах, работаем фейковой
сессией (`scalar`/`scalars` из очередей) и подменённым фасадом `awards`.
Проверяем решения, а не SQL: какие посты считаются откликнутыми, когда
выносится вердикт по «Мемологу» и чем заканчивается 12-часовой рубеж.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import GameMediaPost
from app.services.game import memes
from app.services.game.config import MEME_ALL_REACTORS, MEME_REACTION_WINDOW_MIN

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _FakeSession:
    """Сессия-заглушка: очереди ответов + запись вызовов commit."""

    def __init__(self, *, scalars: list[list] | None = None, scalar=None) -> None:
        self._scalars = list(scalars or [])
        self._scalar = list(scalar or [])
        self.commits = 0

    async def scalar(self, *_a, **_k):
        return self._scalar.pop(0) if self._scalar else None

    async def scalars(self, *_a, **_k):
        return _Rows(self._scalars.pop(0) if self._scalars else [])

    async def commit(self) -> None:
        self.commits += 1


def _post(
    *,
    posted_at: datetime,
    responders: list[int] | None = None,
    window_responders: list[int] | None = None,
    user_id: int = 1,
    resolved_at: datetime | None = None,
) -> GameMediaPost:
    return GameMediaPost(
        id=99,
        chat_id=-100,
        tg_message_id=555,
        user_id=user_id,
        kind="single",
        posted_at=posted_at,
        responders=responders or [],
        window_responders=window_responders or [],
        memelog_done=False,
        resolved_at=resolved_at,
    )


@pytest.fixture
def award_calls(monkeypatch):
    """Записываем вызовы фасада вместо реальных начислений."""
    calls: list[tuple[str, int, dict]] = []

    async def _memelog(_session, user_id, **_kw):
        calls.append(("memelog", user_id, {}))

    async def _reactions(_session, user_id, **_kw):
        calls.append(("reactions", user_id, {}))

    async def _dead(_session, user_id, **kw):
        calls.append(("dead", user_id, kw))

    monkeypatch.setattr(memes.awards, "meme_all_reacted", _memelog)
    monkeypatch.setattr(memes.awards, "meme_reactions", _reactions)
    monkeypatch.setattr(memes.awards, "dead_post", _dead)
    return calls


# --- чистые помощники --------------------------------------------------------

def test_ids_normalizes_none_and_duplicates():
    assert memes._ids(None) == set()
    assert memes._ids([3, 3, 1]) == {1, 3}


def test_memelog_needs_all_live_reactors():
    under = _post(posted_at=NOW, window_responders=list(range(MEME_ALL_REACTORS - 1)))
    exact = _post(posted_at=NOW, window_responders=list(range(MEME_ALL_REACTORS)))
    assert memes._memelog_eligible(under) is False
    assert memes._memelog_eligible(exact) is True


# --- разбор созревших постов -------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_post_is_not_touched(award_calls):
    post = _post(posted_at=NOW - timedelta(minutes=5), window_responders=[2])
    session = _FakeSession(scalars=[[post]])
    stats = await memes.resolve_due(session, now=NOW)
    assert stats == {"checked": 1, "memelog": 0, "alive": 0, "dead": 0, "silent": 0}
    assert award_calls == []
    assert post.memelog_done is False
    assert post.resolved_at is None


@pytest.mark.asyncio
async def test_window_closed_with_all_reactors_awards_memelog(award_calls):
    post = _post(
        posted_at=NOW - timedelta(minutes=MEME_REACTION_WINDOW_MIN + 1),
        window_responders=list(range(MEME_ALL_REACTORS)),
    )
    session = _FakeSession(scalars=[[post]])
    stats = await memes.resolve_due(session, now=NOW)
    assert award_calls == [("memelog", post.user_id, {})]
    assert stats["memelog"] == 1
    # Вердикт вынесен, пост ещё не разрешён (12 часов не прошло).
    assert post.memelog_done is True
    assert post.resolved_at is None


@pytest.mark.asyncio
async def test_window_closed_without_all_reactors_is_silent(award_calls):
    post = _post(
        posted_at=NOW - timedelta(minutes=MEME_REACTION_WINDOW_MIN + 1),
        window_responders=[2, 3],
    )
    session = _FakeSession(scalars=[[post]])
    stats = await memes.resolve_due(session, now=NOW)
    assert award_calls == []
    assert stats["memelog"] == 0
    assert post.memelog_done is True  # повторно не проверяем


@pytest.mark.asyncio
async def test_memelog_verdict_is_not_recomputed(monkeypatch, award_calls):
    post = _post(
        posted_at=NOW - timedelta(hours=2),
        window_responders=list(range(MEME_ALL_REACTORS)),
    )
    post.memelog_done = True
    session = _FakeSession(scalars=[[post]])
    await memes.resolve_due(session, now=NOW)
    # Уже вынесенный вердикт не переигрываем: иначе грант звался бы каждый прогон.
    assert award_calls == []


@pytest.mark.asyncio
async def test_alive_post_counts_success(award_calls):
    post = _post(
        posted_at=NOW - timedelta(hours=13),
        responders=[2, 3],
        window_responders=[2],
    )
    session = _FakeSession(scalars=[[post]])
    stats = await memes.resolve_due(session, now=NOW)
    assert ("reactions", post.user_id, {}) in award_calls
    assert stats["alive"] == 1
    assert post.outcome == memes.OUTCOME_ALIVE
    assert post.resolved_at == NOW


@pytest.mark.asyncio
async def test_dead_post_in_silent_chat_awards_forever_alone(monkeypatch, award_calls):
    post = _post(posted_at=NOW - timedelta(hours=13))
    session = _FakeSession(scalars=[[post]], scalar=[0, 0])

    async def _silent(*_a, **_k):
        return True

    monkeypatch.setattr(memes, "chat_was_silent", _silent)
    stats = await memes.resolve_due(session, now=NOW)
    assert award_calls == [("dead", post.user_id, {"silent_chat": True})]
    assert stats["dead"] == 1 and stats["silent"] == 1
    assert post.outcome == memes.OUTCOME_DEAD


@pytest.mark.asyncio
async def test_dead_post_in_live_chat_skips_forever_alone(monkeypatch, award_calls):
    post = _post(posted_at=NOW - timedelta(hours=13))
    session = _FakeSession(scalars=[[post]])

    async def _noisy(*_a, **_k):
        return False

    monkeypatch.setattr(memes, "chat_was_silent", _noisy)
    stats = await memes.resolve_due(session, now=NOW)
    # «Опиум» начислим (пост без реакций), «Forever alone» — нет (чат был живой).
    assert award_calls == [("dead", post.user_id, {"silent_chat": False})]
    assert stats["silent"] == 0


@pytest.mark.asyncio
async def test_resolved_post_is_skipped(award_calls):
    post = _post(posted_at=NOW - timedelta(hours=30), responders=[2])
    post.resolved_at = NOW - timedelta(hours=18)
    session = _FakeSession(scalars=[[post]])
    stats = await memes.resolve_due(session, now=NOW)
    assert stats["checked"] == 0
    assert award_calls == []


# --- запись постов и откликов -----------------------------------------------

@pytest.mark.asyncio
async def test_record_post_respects_kill_switch(monkeypatch):
    async def _off(_session):
        return False

    monkeypatch.setattr(memes, "is_game_enabled", _off)
    session = _FakeSession()
    assert (
        await memes.record_post(
            session, chat_id=-100, tg_message_id=1, telegram_id=5, kind="single"
        )
        is False
    )
    assert session.commits == 0


@pytest.mark.asyncio
async def test_record_post_is_idempotent(monkeypatch):
    async def _on(_session):
        return True

    monkeypatch.setattr(memes, "is_game_enabled", _on)
    # scalar: сначала PK автора, потом «такой пост уже есть».
    session = _FakeSession(scalar=[7, 42])
    assert (
        await memes.record_post(
            session, chat_id=-100, tg_message_id=1, telegram_id=5, kind="single"
        )
        is False
    )


@pytest.mark.asyncio
async def test_record_post_ignores_strangers(monkeypatch):
    async def _on(_session):
        return True

    monkeypatch.setattr(memes, "is_game_enabled", _on)
    session = _FakeSession(scalar=[None])
    assert (
        await memes.record_post(
            session, chat_id=-100, tg_message_id=1, telegram_id=999, kind="single"
        )
        is False
    )


@pytest.mark.asyncio
async def test_own_message_does_not_count_as_response():
    post = _post(posted_at=NOW, user_id=1)
    session = _FakeSession()
    changed = await memes._touch(session, post, user_id=1, at=NOW)
    assert changed is False
    assert post.responders == []


@pytest.mark.asyncio
async def test_response_inside_window_fills_both_lists():
    post = _post(posted_at=NOW, user_id=1)
    session = _FakeSession()
    changed = await memes._touch(session, post, user_id=2, at=NOW + timedelta(minutes=5))
    assert changed is True
    assert post.responders == [2]
    assert post.window_responders == [2]


@pytest.mark.asyncio
async def test_late_response_counts_but_not_for_memelog():
    post = _post(posted_at=NOW, user_id=1)
    session = _FakeSession()
    await memes._touch(
        session, post, user_id=2, at=NOW + timedelta(minutes=MEME_REACTION_WINDOW_MIN + 5)
    )
    # Пост «живой» (отклик был), но «Мемолог» такие отклики не считает.
    assert post.responders == [2]
    assert post.window_responders == []


@pytest.mark.asyncio
async def test_repeat_response_is_not_recorded_twice():
    post = _post(posted_at=NOW, user_id=1, responders=[2], window_responders=[2])
    session = _FakeSession()
    assert await memes._touch(session, post, user_id=2, at=NOW) is False


@pytest.mark.asyncio
async def test_message_right_after_post_counts(monkeypatch):
    async def _uid(_session, _tg):
        return 2

    monkeypatch.setattr(memes, "_user_id", _uid)
    post = _post(posted_at=NOW - timedelta(minutes=10), user_id=1)
    session = _FakeSession(scalar=[post])
    assert (
        await memes.record_message_response(
            session, chat_id=-100, telegram_id=2, at=NOW
        )
        is True
    )
    assert post.responders == [2]


@pytest.mark.asyncio
async def test_reply_after_window_still_counts(monkeypatch):
    async def _uid(_session, _tg):
        return 3

    monkeypatch.setattr(memes, "_user_id", _uid)
    post = _post(posted_at=NOW - timedelta(hours=5), user_id=1)
    session = _FakeSession(scalar=[post, post])
    assert (
        await memes.record_message_response(
            session,
            chat_id=-100,
            telegram_id=3,
            at=NOW,
            reply_to_tg_message_id=post.tg_message_id,
        )
        is True
    )
    assert post.responders == [3]
    assert post.window_responders == []


@pytest.mark.asyncio
async def test_response_from_stranger_is_ignored(monkeypatch):
    async def _uid(_session, _tg):
        return None

    monkeypatch.setattr(memes, "_user_id", _uid)
    session = _FakeSession()
    assert (
        await memes.record_message_response(session, chat_id=-100, telegram_id=999)
        is False
    )
