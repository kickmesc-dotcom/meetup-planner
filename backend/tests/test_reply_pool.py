"""GHG8 H.1: отдельный пул коротких реплик бота (reply/@-mention).

Прод-фидбек 19.06 #3: на цитату бота он отвечал шизо-цитатой из общего пула →
«в 99% ахинея». Теперь у режима ответа СВОЙ пул (`reply_phrases`), который
курируется в админке, учитывается в снапшоте и мягком скрытии (J.1).

Без БД: паттерн фейк-сессии `admin_config` (как в `test_chukhan_appeal_poll`).
Покрываем: дефолты из фидбека, round-trip get/set, поведение composer'а
(HTML-обёртка, use_counts, скрытие через meta) и тег источника при merge-импорте.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api import routes_admin as ra
from app.services import admin_config as ac
from app.services.admin_config import get_reply_phrases, set_reply_phrases
from app.services.phrase_meta import load_meta, set_flags, source_of
from app.services.phrase_snapshot import apply_snapshot
from app.services.phrase_weights import REPLY_USE_COUNTS_KEY, get_use_counts
from app.services.random_phrases import DEFAULT_REPLY_PHRASES, compose_reply_phrase


class _FakeRow:
    def __init__(self, key: str, value: str) -> None:
        self.key = key
        self.value = value


class _FakeSession:
    def __init__(self) -> None:
        self._store: dict[str, _FakeRow] = {}

    async def get(self, model, key):  # noqa: ANN001
        return self._store.get(key)

    def add(self, row) -> None:  # noqa: ANN001
        self._store[row.key] = row

    async def commit(self) -> None:
        pass


@pytest.fixture
def session(monkeypatch):
    s = _FakeSession()
    monkeypatch.setattr(ac, "AdminConfig", _FakeRow)
    return s


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(ra, "get_settings", lambda: SimpleNamespace(admin_tg_id_set={777}))
    user = MagicMock()
    user.telegram_id = 777
    user.id = 42
    return user


def test_default_pool_matches_feedback():
    # 19.06 #3: ровно те реплики, что прислал пользователь.
    assert len(DEFAULT_REPLY_PHRASES) == 10
    assert len(set(DEFAULT_REPLY_PHRASES)) == 10
    assert all(p.strip() for p in DEFAULT_REPLY_PHRASES)
    assert "Так точно 🫡" in DEFAULT_REPLY_PHRASES
    assert "Да не ной бля" in DEFAULT_REPLY_PHRASES


@pytest.mark.asyncio
async def test_get_returns_default_when_absent(session):
    assert await get_reply_phrases(session) == list(DEFAULT_REPLY_PHRASES)


@pytest.mark.asyncio
async def test_set_then_get_roundtrip(session):
    await set_reply_phrases(session, ["один", "один", "  два  "])
    # дедуп + strip, как у остальных пулов
    assert await get_reply_phrases(session) == ["один", "два"]


@pytest.mark.asyncio
async def test_compose_wraps_in_italics_and_tracks_use(session):
    await set_reply_phrases(session, ["только эта"])
    out = await compose_reply_phrase(session)
    assert out == "<i>только эта</i>"
    counts = await get_use_counts(session, REPLY_USE_COUNTS_KEY)
    assert sum(counts.values()) == 1


@pytest.mark.asyncio
async def test_compose_respects_hidden_phrases(session):
    await set_reply_phrases(session, ["скрытая", "видимая"])
    await set_flags(session, "reply_phrases", "скрытая", hidden=True)
    for _ in range(20):
        assert await compose_reply_phrase(session) == "<i>видимая</i>"


@pytest.mark.asyncio
async def test_compose_returns_none_on_empty_pool(session):
    await set_reply_phrases(session, [])
    assert await compose_reply_phrase(session) is None


@pytest.mark.asyncio
async def test_snapshot_merge_tags_reply_pool_as_ai(session):
    snap = {
        "format": "meetup-planner.phrase-snapshot",
        "version": 1,
        "pools": {"reply_phrases": ["свежая реплика"]},
    }
    summary = await apply_snapshot(session, snap, mode="merge", source="ai")
    assert summary["pools"]["reply_phrases"]["added"] == 1
    assert "свежая реплика" in await get_reply_phrases(session)
    assert source_of(await load_meta(session), "reply_phrases", "свежая реплика") == "ai"


@pytest.mark.asyncio
async def test_admin_endpoints_roundtrip(session, admin):
    out = await ra.admin_put_reply_phrases(ra.ReplyPhrasesIO(phrases=["а", "б"]), session, admin)
    assert out.phrases == ["а", "б"]
    got = await ra.admin_get_reply_phrases(session, admin)
    assert got.phrases == ["а", "б"]
