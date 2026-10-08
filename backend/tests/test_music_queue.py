"""GHG11(9): очередь плеера (подборки подряд), «только лайкнутые» и уведомления.

БД-стенда в проекте нет, поэтому работаем фейк-сессиями: очереди ответов
`scalars`/`execute`/`scalar`. Проверяем именно нашу логику — порядок плейлистов,
подстановку лайков, создание уведомления автору (и НЕсоздание для своего трека),
а также тексты/имена, которые иначе пришлось бы смотреть руками в проде.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.routes_game import _music_playlist_title, _music_track_out
from app.api.routes_users import NotificationOut, _payload_track_id
from app.db.models import AppNotification, MusicTrack, MusicTrackLike, User
from app.services import notifications
from app.services.game import music

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# фейк-сессии (стиль tests/test_game_music_likes.py)
# --------------------------------------------------------------------------
class _Rows:
    """Как `ScalarResult`/`ChunkedIteratorResult`: и `.all()`, и итерация."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _Session:
    """Сессия с очередями ответов: scalars/execute/scalar + add/commit/flush."""

    def __init__(self, *, scalars=None, rows=None, values=None, rowcount: int = 0):
        self.scalars_queue = list(scalars or [])
        self.execute_queue = list(rows or [])
        self.scalar_queue = list(values or [])
        self.rowcount = rowcount
        self.added: list = []
        self.deleted: list = []
        self.commits = 0

    async def scalars(self, *_a, **_k):  # noqa: ANN002, ANN003
        return _Rows(self.scalars_queue.pop(0) if self.scalars_queue else [])

    async def execute(self, *_a, **_k):  # noqa: ANN002, ANN003
        return _Rows(self.execute_queue.pop(0) if self.execute_queue else [])

    async def scalar(self, *_a, **_k):  # noqa: ANN002, ANN003
        return self.scalar_queue.pop(0) if self.scalar_queue else None

    async def get(self, *_a, **_k):  # noqa: ANN002, ANN003
        return self.added_get if hasattr(self, "added_get") else None

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)

    async def delete(self, row) -> None:  # noqa: ANN001
        self.deleted.append(row)

    async def commit(self) -> None:
        self.commits += 1


class _ResultRowcount:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _CountSession(_Session):
    """Для `mark_read`: `execute` отдаёт объект с `rowcount`."""

    async def execute(self, *_a, **_k):  # noqa: ANN002, ANN003
        return _ResultRowcount(self.rowcount)


def _track(tid: int, *, user_id: int = 1, title: str = "трек", status: str = "published"):
    return MusicTrack(
        id=tid, user_id=user_id, kind="audio", title=title, status=status
    )


def _selection(sid: int, at: datetime = NOW):
    return SimpleNamespace(id=sid, created_at=at, track_count=2, note="published")


# --------------------------------------------------------------------------
# очередь подборок
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_queue_playlists_keeps_order_and_tracks():
    """Свежая подборка первой, треки — свои для каждой (порядок = очередь)."""
    fresh, older = _selection(12), _selection(11, NOW.replace(day=1))
    t1, t2 = _track(1), _track(2)
    session = _Session(scalars=[[fresh, older], [t1, t2], [t1]])
    got = await music.queue_playlists(session, limit=5)
    assert [sel.id for sel, _ in got] == [12, 11]
    assert [t.id for t in got[0][1]] == [1, 2]
    assert [t.id for t in got[1][1]] == [1]


@pytest.mark.asyncio
async def test_queue_playlists_empty_when_nothing_published():
    session = _Session(scalars=[[]])
    assert await music.queue_playlists(session) == []


@pytest.mark.asyncio
async def test_liked_tracks_returns_published_only():
    session = _Session(scalars=[[_track(3)]])
    got = await music.liked_tracks(session, 7, limit=50)
    assert [t.id for t in got] == [3]


# --------------------------------------------------------------------------
# уведомление автору о лайке
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_like_notifies_track_author():
    session = _Session(values=[None, 1])  # нет прежнего лайка, затем count=1
    session.added_get = _track(5, user_id=1, title="Гимн чата")
    res = await music.toggle_like(session, user_id=7, track_id=5, liker_name="Митян")
    assert res.liked is True

    notes = [r for r in session.added if isinstance(r, AppNotification)]
    assert len(notes) == 1
    note = notes[0]
    assert note.user_id == 1  # автор трека
    assert note.kind == notifications.KIND_MUSIC_LIKE
    assert "Митян" in note.text and "Гимн чата" in note.text
    assert note.payload == {"track_id": 5}
    # лайк и уведомление коммитятся одной транзакцией
    assert session.commits == 1


@pytest.mark.asyncio
async def test_like_own_track_creates_no_notification():
    """Свой трек — не новость для себя."""
    session = _Session(values=[None, 1])
    session.added_get = _track(5, user_id=7)
    await music.toggle_like(session, user_id=7, track_id=5, liker_name="Митян")
    assert [r for r in session.added if isinstance(r, AppNotification)] == []


@pytest.mark.asyncio
async def test_unlike_creates_no_notification():
    session = _Session(values=[MusicTrackLike(user_id=7, track_id=5), 0])
    session.added_get = _track(5, user_id=1)
    res = await music.toggle_like(session, user_id=7, track_id=5, liker_name="Митян")
    assert res.liked is False
    assert [r for r in session.added if isinstance(r, AppNotification)] == []


@pytest.mark.asyncio
async def test_like_without_name_still_writes_something_readable():
    """Имени может не быть (старый клиент) — текст должен остаться осмысленным."""
    session = _Session(values=[None, 1])
    session.added_get = _track(5, user_id=1)
    await music.toggle_like(session, user_id=7, track_id=5)
    note = next(r for r in session.added if isinstance(r, AppNotification))
    assert "Кто-то" in note.text


# --------------------------------------------------------------------------
# сервис уведомлений
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_notifications_add_sets_payload_and_defaults():
    session = _Session()
    row = await notifications.add(
        session,
        user_id=3,
        kind=notifications.KIND_MUSIC_LIKE,
        text="❤️ тест",
    )
    assert row.payload == {} and row.user_id == 3
    assert session.added == [row]


@pytest.mark.asyncio
async def test_unread_count_is_int():
    session = _Session(values=[2])
    assert await notifications.unread_count(session, 1) == 2
    session = _Session(values=[None])
    assert await notifications.unread_count(session, 1) == 0


@pytest.mark.asyncio
async def test_mark_read_returns_changed_rows():
    session = _CountSession(rowcount=3)
    assert await notifications.mark_read(session, 1, all_=True) == 3
    assert session.commits == 1


@pytest.mark.asyncio
async def test_mark_read_without_ids_does_nothing():
    """Пустой список id — не «отметить всё»: без `all_` ничего не трогаем."""
    session = _CountSession(rowcount=3)
    assert await notifications.mark_read(session, 1, ids=[]) == 0
    assert session.commits == 0


# --------------------------------------------------------------------------
# helpers роутов
# --------------------------------------------------------------------------
def test_music_track_out_fills_likes_and_flag():
    out = _music_track_out(_track(5, title="Т"), {5: 4}, {5})
    assert (out.id, out.likes, out.liked) == (5, 4, True)
    other = _music_track_out(_track(6), {}, set())
    assert (other.likes, other.liked) == (0, False)


def test_music_playlist_title_names_first_week_and_dates_rest():
    assert _music_playlist_title(0, NOW) == "Подборка недели"
    assert _music_playlist_title(1, NOW) == "Подборка от 08.10.2026"
    assert _music_playlist_title(2, None) == "Прошлая подборка"


def test_payload_track_id_survives_garbage():
    assert _payload_track_id({"track_id": 5}) == 5
    assert _payload_track_id({"track_id": "5"}) is None
    assert _payload_track_id({}) is None
    assert _payload_track_id(None) is None


def test_notification_out_shape_is_what_the_bell_needs():
    out = NotificationOut(
        id=1,
        kind="music_like",
        text="❤️ Митян лайкнул твой трек «X»",
        track_id=5,
        created_at=NOW,
        read=False,
    )
    assert out.model_dump()["track_id"] == 5
    assert out.read is False


def test_user_model_has_display_name_for_notification_text():
    """Имя лайкающего роут берёт из `CurrentUser` — убеждаемся, что поле есть."""
    assert "display_name" in User.__table__.columns
