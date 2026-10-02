"""GHG10 Э14: голосовые задания — чистая логика и приём сдачи.

БД-стенда в проекте нет, поэтому:

* время/окно, выбор задания и тексты — чистыми функциями;
* `submit` — через фейк-сессию с очередью ответов `scalar`, а награда и журнал
  подменены: проверяем РЕШЕНИЕ (принять/отклонить), а не запись в БД.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import EventLog, GameVoiceSubmission, GameVoiceTask
from app.services.game import voice
from app.services.game.config import (
    VOICE_DAY_END_HOUR,
    VOICE_DAY_START_HOUR,
    VOICE_POLL_REWARD,
    VOICE_REWARD,
    VOICE_TZ_OFFSET_HOURS,
)
from app.services.game.voice_catalog import TASKS

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Чистая часть
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "utc_hour,expected_local",
    [(0, 3), (6, 9), (7, 10), (16, 19), (17, 20), (21, 0), (22, 1)],
)
def test_local_hour_shifts_by_chat_offset(utc_hour, expected_local):
    moment = datetime(2026, 9, 30, utc_hour, 0, tzinfo=timezone.utc)
    assert voice.local_hour(moment) == (utc_hour + VOICE_TZ_OFFSET_HOURS) % 24
    assert voice.local_hour(moment) == expected_local


def test_is_daytime_boundaries():
    """Никаких «активностей в два часа ночи», и верхняя граница исключающая."""
    def at(utc_hour: int) -> datetime:
        return datetime(2026, 9, 30, utc_hour, 0, tzinfo=timezone.utc)

    # local = utc + 3; границы 10..20 (20 — уже нет).
    assert voice.is_daytime(at(7)) is True  # local 10
    assert voice.is_daytime(at(6)) is False  # local 9
    assert voice.is_daytime(at(16)) is True  # local 19
    assert voice.is_daytime(at(17)) is False  # local 20
    assert VOICE_DAY_START_HOUR == 10 and VOICE_DAY_END_HOUR == 20


def test_pick_task_respects_cooldown():
    all_codes = {t.code for t in TASKS}
    rng = random.Random(1)
    # Одно задание свободно — берём именно его.
    free = list(all_codes - {"duck"})
    assert voice.pick_task(used_codes=set(free), rng=rng).code == "duck"
    # Все на кулдауне — None (а не падение и не повтор).
    assert voice.pick_task(used_codes=all_codes, rng=rng) is None


def test_build_task_text_has_window_reward_and_dm_hint():
    task = TASKS[0]
    expires = NOW + timedelta(minutes=task.window_minutes)
    text = voice.build_task_text(task, expires_at=expires, bot_username="ghgbot")
    assert task.text in text
    assert f"+{task.reward} XP" in text
    assert "@ghgbot" in text
    assert "реплаем" in text
    # Условия участия явные: один вариант с человека, все успевают до закрытия.
    assert "один с человека" in text and "до закрытия" in text
    # Без username — без «@None», просто «боту в личку».
    fallback = voice.build_task_text(task, expires_at=expires, bot_username=None)
    assert "@None" not in fallback and "боту в личку" in fallback


def test_summary_header_and_caption():
    assert "никто не прислал" in voice.summary_header(title="Дак", count=0)
    header = voice.summary_header(title="Дак", count=3)
    assert "Дак" in header and "3" in header
    assert voice.variant_caption(index=2, name="Митян") == "№2 — <b>Митян</b>"


@pytest.mark.parametrize(
    "counts,expected",
    [
        ([0, 0, 0], None),
        ([], None),
        ([1, 3, 2], 1),
        ([2, 2], 0),  # равенство — меньший индекс (раньше сдал)
        ([0, 1], 1),
        ([5, 1], 0),
    ],
)
def test_pick_winner_index(counts, expected):
    assert voice.pick_winner_index(counts) == expected


# --------------------------------------------------------------------------
# Приём сдачи (фейк-сессия)
# --------------------------------------------------------------------------


class _Rows:
    def __init__(self, rows: list):
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self, scalars: list | None = None, *, fail_commit: bool = False):
        self.scalar_queue = list(scalars or [])
        self.added: list = []
        self.commits = 0
        self.rolled = 0
        self.fail_commit = fail_commit
        # Очередь ответов `scalars` (для `_submissions` в `finalize_task`).
        self.scalars_queue: list[list] = []

    async def scalar(self, *_a, **_k):  # noqa: ANN002, ANN003
        return self.scalar_queue.pop(0) if self.scalar_queue else None

    async def scalars(self, *_a, **_k):  # noqa: ANN002, ANN003
        return _Rows(self.scalars_queue.pop(0) if self.scalars_queue else [])

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)

    async def commit(self) -> None:
        if self.fail_commit:
            raise IntegrityError("stmt", {}, Exception("duplicate"))
        self.commits += 1

    async def rollback(self) -> None:
        self.rolled += 1


def _task(
    *, closed: bool = False, expired: bool = False, task_id: int | None = None
) -> GameVoiceTask:
    return GameVoiceTask(
        id=task_id,
        chat_id=-100,
        code="duck",
        text="задание",
        reward=VOICE_REWARD,
        tg_message_id=55,
        expires_at=NOW - timedelta(minutes=1) if expired else NOW + timedelta(hours=3),
        closed_at=NOW if closed else None,
    )


@pytest.fixture
def no_io(monkeypatch):
    async def _noop(*_a, **_k):  # noqa: ANN002, ANN003
        return None

    monkeypatch.setattr(voice.awards, "voice", _noop)
    monkeypatch.setattr(voice.journal, "announce", _noop)


@pytest.mark.asyncio
async def test_submit_without_task(no_io):
    session = _FakeSession([None])
    res = await voice.submit(session, telegram_id=1, file_id="f", at=NOW)
    assert res.status == voice.NO_TASK


@pytest.mark.asyncio
async def test_submit_to_closed_task(no_io):
    session = _FakeSession([_task(closed=True)])
    res = await voice.submit(
        session, telegram_id=1, file_id="f", reply_to_message_id=55, at=NOW
    )
    assert res.status == voice.CLOSED


@pytest.mark.asyncio
async def test_submit_to_expired_task(no_io):
    session = _FakeSession([_task(expired=True)])
    res = await voice.submit(
        session, telegram_id=1, file_id="f", reply_to_message_id=55, at=NOW
    )
    assert res.status == voice.CLOSED


@pytest.mark.asyncio
async def test_submit_from_unknown_user(no_io):
    session = _FakeSession([_task(), None])  # задание есть, юзера нет
    res = await voice.submit(
        session, telegram_id=999, file_id="f", reply_to_message_id=55, at=NOW
    )
    assert res.status == voice.UNKNOWN_USER


@pytest.mark.asyncio
async def test_submit_ok_awards_and_records(no_io):
    session = _FakeSession([_task(), 5, "Митян"])
    res = await voice.submit(
        session, telegram_id=111, file_id="file-1", duration=4,
        tg_message_id=77, reply_to_message_id=55, at=NOW,
    )
    assert res.status == voice.OK
    assert res.reward == VOICE_REWARD
    assert res.name == "Митян"
    assert session.commits == 1
    saved = [r for r in session.added if isinstance(r, GameVoiceSubmission)]
    assert len(saved) == 1 and saved[0].file_id == "file-1"


@pytest.mark.asyncio
async def test_submit_ok_does_not_double_post(monkeypatch):
    """Одну сдачу сопровождает ОДНО сообщение (ответ хендлера), а не два.

    Раньше `submit` ещё и звал `journal.announce` («X сдал вариант…»), и на одну
    голосовуху уходило два почти одинаковых сообщения. Теперь анонс — дело
    хендлера, поэтому из сервиса в журнал ничего не летит.
    """
    calls: list = []

    async def _noop(*_a, **_k):  # noqa: ANN002, ANN003
        return None

    async def _record(*_a, **_k):  # noqa: ANN002, ANN003
        calls.append(_k)
        return True

    monkeypatch.setattr(voice.awards, "voice", _noop)
    monkeypatch.setattr(voice.journal, "announce", _record)
    session = _FakeSession([_task(), 5, "Митян"])
    res = await voice.submit(
        session, telegram_id=111, file_id="f", reply_to_message_id=55, at=NOW
    )
    assert res.status == voice.OK
    assert calls == []


@pytest.mark.asyncio
async def test_submit_second_variant_is_rejected(no_io):
    session = _FakeSession([_task(), 5, "Митян"], fail_commit=True)
    res = await voice.submit(
        session, telegram_id=111, file_id="file-2", reply_to_message_id=55, at=NOW
    )
    assert res.status == voice.ALREADY
    assert session.rolled == 1


@pytest.mark.asyncio
async def test_finalize_is_idempotent(no_io):
    task = _task()
    session = _FakeSession()
    assert await voice.finalize_task(session, None, task, now=NOW) is True
    assert task.closed_at == NOW and task.outcome == "summary"
    # Повтор (рестарт/повторный тик) — ничего не делает.
    assert await voice.finalize_task(session, None, task, now=NOW) is False


def test_voice_poll_reward_is_the_bonus_from_the_brief():
    assert VOICE_POLL_REWARD == 50


# --------------------------------------------------------------------------
# Альтернативный режим-«рулетка»: иногда награда только первому
# --------------------------------------------------------------------------


def test_pick_task_mode_toggle():
    rng = random.Random(1)
    # Рубильник выкл — всегда «участвуют все».
    assert voice.pick_task_mode(enabled=False, rng=rng) == voice.MODE_ALL
    # 0% — тоже все; 100% — всегда только первый.
    assert voice.pick_task_mode(enabled=True, percent=0, rng=rng) == voice.MODE_ALL
    assert voice.pick_task_mode(enabled=True, percent=100, rng=rng) == voice.MODE_FIRST_ONLY


def test_pick_task_mode_is_a_rough_coin_flip():
    rng = random.Random(7)
    picks = [voice.pick_task_mode(enabled=True, percent=50, rng=rng) for _ in range(400)]
    firsts = picks.count(voice.MODE_FIRST_ONLY)
    # Не строгая статистика: просто оба исхода возможны и нет перекоса.
    assert 120 < firsts < 280


def test_build_task_text_first_only_terms():
    task = TASKS[0]
    expires = NOW + timedelta(minutes=task.window_minutes)
    text = voice.build_task_text(
        task, expires_at=expires, bot_username=None, mode=voice.MODE_FIRST_ONLY
    )
    assert "только первому" in text
    assert "первому сдавшему" in text
    # В режиме «все» этих условий нет.
    all_text = voice.build_task_text(
        task, expires_at=expires, bot_username=None, mode=voice.MODE_ALL
    )
    assert "только первому" not in all_text
    assert "один с человека" in all_text


def _mode_row(task_id: int = 1) -> EventLog:
    return EventLog(
        kind=voice.MODE_KIND, payload={"task_id": task_id, "mode": voice.MODE_FIRST_ONLY}
    )


def _submission(*, minutes_ago: int, user_id: int = 7) -> GameVoiceSubmission:
    return GameVoiceSubmission(
        task_id=1,
        user_id=user_id,
        file_id="first",
        submitted_at=NOW - timedelta(minutes=minutes_ago),
    )


@pytest.mark.asyncio
async def test_get_task_mode_defaults_to_all(no_io):
    assert await voice.get_task_mode(_FakeSession([None]), 1) == voice.MODE_ALL
    # Нет id (не сохранено) — тоже дефолт, без обращения к БД.
    assert await voice.get_task_mode(_FakeSession([]), None) == voice.MODE_ALL


@pytest.mark.asyncio
async def test_first_only_first_submitter_is_rewarded(no_io):
    session = _FakeSession(
        [_task(task_id=1), 5, "Митян", _mode_row(), None]  # вариантов ещё нет
    )
    res = await voice.submit(
        session, telegram_id=111, file_id="f", reply_to_message_id=55, at=NOW
    )
    assert res.status == voice.OK and res.reward == VOICE_REWARD


@pytest.mark.asyncio
async def test_first_only_latecomer_within_grace_is_told(no_io):
    session = _FakeSession(
        [
            _task(task_id=1),
            222,
            "Поздний",
            _mode_row(),
            _submission(minutes_ago=10, user_id=7),
            "Митян",
        ]
    )
    res = await voice.submit(
        session, telegram_id=222, file_id="late", reply_to_message_id=55, at=NOW
    )
    assert res.status == voice.LATE
    assert res.name == "Митян"  # имя ПЕРВОГО, чтобы опоздавший понял, кто успел


@pytest.mark.asyncio
async def test_first_only_after_grace_is_silent(no_io):
    session = _FakeSession(
        [_task(task_id=1), 222, "Поздний", _mode_row(), _submission(minutes_ago=120)]
    )
    res = await voice.submit(
        session, telegram_id=222, file_id="late", reply_to_message_id=55, at=NOW
    )
    assert res.status == voice.SILENT


@pytest.mark.asyncio
async def test_first_only_owner_resubmit_is_already(no_io):
    # Первый сдавший шлёт ещё раз — напоминаем «один на участника», а не «поздняк».
    session = _FakeSession(
        [_task(task_id=1), 7, "Митян", _mode_row(), _submission(minutes_ago=5, user_id=7)]
    )
    res = await voice.submit(
        session, telegram_id=7, file_id="again", reply_to_message_id=55, at=NOW
    )
    assert res.status == voice.ALREADY
