"""GHG11(12): состояние задания в ленте и персональное «просмотрено».

Оператор: «открытые задания подсвечиваем манящим зеленоватым, закрытые —
тускнеют с замком; закрытые без заявок — тусклые и красные, крупно
"поучаствовало 0"; закрытые с заявками — жёлтые и с пометкой непросмотрено,
после просмотра — просмотрено и затухают».

Здесь проверяется серверная половина: `feed.task_state` (чистая функция),
`feed._task_block` (какую запись считать заданием) и персональная пометка
`feed_moderation.seen_item_ids/mark_seen` на фейковой сессии.
"""
from __future__ import annotations

from datetime import UTC

import pytest
from sqlalchemy.dialects import postgresql

from app.services.game import feed
from app.services.game import feed_moderation as fm

# --------------------------------------------------------------- состояние ---


def test_open_task_is_open():
    assert feed.task_state(closed=False, participants=0)["state"] == feed.TASK_OPEN


def test_closed_without_participants_is_empty():
    state = feed.task_state(closed=True, participants=0)
    assert state["state"] == feed.TASK_EMPTY
    assert state["participants"] == 0
    assert state["closed"] is True
    assert state["seen"] is False


def test_closed_with_participants_is_filled():
    state = feed.task_state(closed=True, participants=3, seen=True)
    assert state["state"] == feed.TASK_FILLED
    assert state["participants"] == 3
    assert state["seen"] is True


def test_negative_participants_clamped():
    """Отрицательное число участников — это «никто», а не «минус один»."""
    assert feed.task_state(closed=True, participants=-2)["participants"] == 0


# ------------------------------------------------------------ блок задания ---


def _item(kind: str, row_id: str) -> dict:
    return feed._item(
        source="test", row_id=row_id, kind=kind, at=None, text="", user=None
    )


def test_voice_item_with_submissions_is_filled_and_seen():
    item = _item(feed.FEED_VOICE, "voice:3")
    detail = {
        "closed": True,
        "submissions": [{"id": 1, "user_id": 5}, {"id": 2, "user_id": 6}],
    }
    block = feed._task_block(item=item, detail=detail, seen=True)
    assert block is not None
    assert block["state"] == feed.TASK_FILLED
    assert block["participants"] == 2
    assert block["seen"] is True


def test_voice_item_open_is_open():
    item = _item(feed.FEED_VOICE, "voice:4")
    block = feed._task_block(
        item=item, detail={"closed": False, "submissions": []}, seen=False
    )
    assert block is not None
    assert block["state"] == feed.TASK_OPEN


def test_voice_item_closed_without_submissions_is_empty():
    item = _item(feed.FEED_VOICE, "voice:5")
    block = feed._task_block(
        item=item, detail={"closed": True, "submissions": []}, seen=False
    )
    assert block is not None
    assert block["state"] == feed.TASK_EMPTY
    assert block["participants"] == 0


def test_event_announcement_uses_activity_participants():
    item = _item("event", "journal:9")
    detail = {"activity": {"closed": True, "participants": 1}}
    block = feed._task_block(item=item, detail=detail, seen=False)
    assert block is not None
    assert block["state"] == feed.TASK_FILLED
    assert block["participants"] == 1


def test_event_announcement_closed_and_ignored_is_empty():
    item = _item("event", "journal:9")
    block = feed._task_block(
        item=item, detail={"activity": {"closed": True, "participants": 0}}, seen=False
    )
    assert block is not None
    assert block["state"] == feed.TASK_EMPTY


def test_plain_event_without_activity_is_not_a_task():
    """Обычный журнальный анонс (без карточки участия) заданием не считаем."""
    assert feed._task_block(item=_item("event", "journal:9"), detail={}, seen=False) is None


def test_other_kinds_are_not_tasks():
    assert feed._task_block(item=_item("achievement", "ach:1"), detail={}, seen=False) is None


# ------------------------------------------------- activity_detail: счётчик ---


def test_activity_detail_reports_participants():
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    now = datetime.now(UTC)
    won = SimpleNamespace(
        id=1,
        code="c",
        text="t",
        answers=[{"matcher": "^да$", "xp": 10, "label": "да", "media": False}],
        created_at=now,
        expires_at=now + timedelta(minutes=30),
        closed_at=now,
        winner_user_id=5,
    )
    detail = feed.activity_detail(won, user_id=1, now=now)
    assert detail["participants"] == 1
    assert detail["winner_user_id"] == 5

    empty = SimpleNamespace(**{**won.__dict__, "winner_user_id": None})
    assert feed.activity_detail(empty, user_id=1, now=now)["participants"] == 0


# --------------------------------------------- «просмотрено»: SQL и no-op ----


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeSession:
    """Минимальная сессия: запоминает добавленные EventLog и отдаёт строки."""

    def __init__(self, seen_rows: list[str] | None = None):
        self.seen_rows = seen_rows or []
        self.added: list[object] = []
        self.committed = 0
        self.statements: list[object] = []

    async def scalars(self, stmt):
        self.statements.append(stmt)
        return _FakeScalars(self.seen_rows)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def execute(self, stmt):
        self.statements.append(stmt)
        return None

    async def commit(self) -> None:
        self.committed += 1


@pytest.mark.asyncio
async def test_seen_item_ids_reads_user_scoped_rows():
    session = _FakeSession(["voice:3", None, "journal:9"])
    ids = await fm.seen_item_ids(session, 5)
    assert ids == {"voice:3", "journal:9"}
    # Запрос обязан быть отфильтрован по пользователю, а не глобальным.
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "event_log.payload" in sql
    assert fm.SEEN_KIND in compiled.params.values()
    assert 5 in compiled.params.values()


@pytest.mark.asyncio
async def test_mark_seen_is_idempotent():
    session = _FakeSession([])
    await fm.mark_seen(session, item_id="voice:3", user_id=5)
    assert len(session.added) == 1
    log_row = session.added[0]
    assert log_row.kind == fm.SEEN_KIND
    assert log_row.payload == {"item_id": "voice:3", "user_id": 5}

    # Повторно — ничего не пишем (иначе лента «перечёркивала» бы выбор).
    session.seen_rows = ["voice:3"]
    await fm.mark_seen(session, item_id="voice:3", user_id=5)
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_unmark_seen_clears_flag():
    session = _FakeSession([])
    await fm.unmark_seen(session, item_id="voice:3", user_id=5)
    assert session.committed == 1
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    values = set(compiled.params.values())
    assert "voice:3" in values
    assert fm.SEEN_KIND in values
    assert 5 in values
