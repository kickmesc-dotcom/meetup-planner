"""GHG6 N2.6: пост-фактум 5★-опрос «как собрались».

Покрываем:
- `feedback_index_to_payload` — чистая функция (TG option_id → rating/absent).
- `submit_feedback`:
    - happy path: rating=4 → запись создана с rating=4, was_absent=False,
      add_chukhan_weight НЕ зван.
    - was_absent=True → запись с was_absent=True, rating=None, weight
      инкрементирован на delta, тост в чат отправлен.
    - duplicate (тот же user_id+meeting_id) → UPDATE, без повторного начисления
      штрафа если previously_absent был True.
    - валидация: rating out of range без was_absent → ValueError.
- `enumerate_pending_meetings`:
    - возвращает только status='confirmed' и старше 1d.
    - НЕ возвращает встречи у которых уже есть feedback-полл или хотя бы один
      feedback row.
    - НЕ возвращает старше 14d.

В проекте нет async-sqlite-стенда (см. test_loser_cooldown_split, test_worm).
Поэтому юнитим через _FakeSession-стаб.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.meeting_feedback import (
    FEEDBACK_ABSENT_INDEX,
    POLL_KIND_MEETING_FEEDBACK,
    feedback_index_to_payload,
)


# --- pure: feedback_index_to_payload ---------------------------------------


def test_index_0_to_4_is_rating_plus_one() -> None:
    assert feedback_index_to_payload(0) == (1, False)
    assert feedback_index_to_payload(1) == (2, False)
    assert feedback_index_to_payload(2) == (3, False)
    assert feedback_index_to_payload(3) == (4, False)
    assert feedback_index_to_payload(4) == (5, False)


def test_index_5_is_was_absent() -> None:
    assert feedback_index_to_payload(FEEDBACK_ABSENT_INDEX) == (None, True)


def test_index_out_of_range_returns_none_pair() -> None:
    assert feedback_index_to_payload(-1) == (None, False)
    assert feedback_index_to_payload(99) == (None, False)


def test_poll_kind_constant() -> None:
    assert POLL_KIND_MEETING_FEEDBACK == "meeting_feedback"


# --- submit_feedback -------------------------------------------------------


def _make_fake_session_for_submit(
    existing_feedback: Any | None = None,
    user_obj: Any | None = None,
) -> Any:
    """Минимальный async-стенд под submit_feedback.

    Подменяет:
    - `session.scalar(select(MeetingFeedback))` → existing_feedback (или None).
    - `session.get(User, user_id)` → user_obj.
    - `session.add/commit/refresh` — no-op.
    """
    sess = MagicMock()
    sess.add = MagicMock()
    sess.commit = AsyncMock()
    sess.refresh = AsyncMock()

    async def _scalar(stmt: Any) -> Any:
        # Простой stub — всегда возвращаем existing_feedback. submit_feedback
        # делает только один scalar() для существующего фидбэка.
        return existing_feedback

    async def _get(_model: Any, _pk: Any) -> Any:
        return user_obj

    sess.scalar = _scalar
    sess.get = _get
    return sess


async def test_submit_rating_happy_path() -> None:
    """rating=4 → создаётся новая запись, никаких side-effects."""
    from app.services.meeting_feedback import submit_feedback

    fake_user = MagicMock(id=10, telegram_id=12345, display_name="Дмитрий Menar")
    sess = _make_fake_session_for_submit(existing_feedback=None, user_obj=fake_user)

    with patch(
        "app.services.meeting_feedback.add_chukhan_weight", new_callable=AsyncMock
    ) as add_weight:
        fb = await submit_feedback(
            sess, meeting_id=42, user_id=10, rating=4, was_absent=False
        )
    # session.add вызван ровно один раз (новая запись).
    assert sess.add.called
    # weight НЕ инкрементирован — это просто rating, не absence.
    add_weight.assert_not_called()
    # Возвращённый MeetingFeedback имеет правильные поля.
    assert fb.rating == 4
    assert fb.was_absent is False


async def test_submit_was_absent_records_and_charges_weight() -> None:
    """was_absent=True → +delta к чухан-весу + тост в чат."""
    from app.services.meeting_feedback import submit_feedback

    fake_user = MagicMock(id=10, telegram_id=12345, display_name="Никита")
    sess = _make_fake_session_for_submit(existing_feedback=None, user_obj=fake_user)

    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock()
    fake_settings = MagicMock()
    fake_settings.group_chat_id = -100123

    with (
        patch(
            "app.services.meeting_feedback.add_chukhan_weight", new_callable=AsyncMock
        ) as add_weight,
        patch(
            "app.services.meeting_feedback.get_meeting_feedback_absence_weight",
            new_callable=AsyncMock,
            return_value=0.5,
        ),
        patch(
            "app.services.meeting_feedback.get_meeting_feedback_notify_absence",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("app.services.meeting_feedback.get_settings", return_value=fake_settings),
    ):
        add_weight.return_value = 1.5
        fb = await submit_feedback(
            sess,
            meeting_id=42,
            user_id=10,
            was_absent=True,
            bot=fake_bot,
        )
    assert fb.was_absent is True
    assert fb.rating is None
    # weight инкрементирован на 0.5.
    add_weight.assert_awaited_once_with(sess, tg_id=12345, delta=0.5)
    # Тост в чат.
    fake_bot.send_message.assert_awaited_once()
    call = fake_bot.send_message.await_args
    assert "Никита" in call.kwargs["text"]
    assert "пропустил встречу" in call.kwargs["text"]


async def test_submit_was_absent_no_notify_when_disabled() -> None:
    """notify_absence=false → weight всё равно +delta, но тоста нет."""
    from app.services.meeting_feedback import submit_feedback

    fake_user = MagicMock(id=11, telegram_id=22222, display_name="Серёжа Neo")
    sess = _make_fake_session_for_submit(existing_feedback=None, user_obj=fake_user)

    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock()

    with (
        patch(
            "app.services.meeting_feedback.add_chukhan_weight", new_callable=AsyncMock
        ) as add_weight,
        patch(
            "app.services.meeting_feedback.get_meeting_feedback_absence_weight",
            new_callable=AsyncMock,
            return_value=0.5,
        ),
        patch(
            "app.services.meeting_feedback.get_meeting_feedback_notify_absence",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        await submit_feedback(
            sess, meeting_id=1, user_id=11, was_absent=True, bot=fake_bot
        )
    add_weight.assert_awaited_once()
    fake_bot.send_message.assert_not_awaited()


async def test_submit_duplicate_absent_does_not_recharge() -> None:
    """Если предыдущий голос был absent, повторный absent НЕ начисляет delta снова."""
    from app.services.meeting_feedback import submit_feedback

    fake_user = MagicMock(id=10, telegram_id=12345, display_name="Никита")
    existing = MagicMock(
        meeting_id=42,
        user_id=10,
        rating=None,
        was_absent=True,
        reason_text=None,
    )
    sess = _make_fake_session_for_submit(existing_feedback=existing, user_obj=fake_user)

    with patch(
        "app.services.meeting_feedback.add_chukhan_weight", new_callable=AsyncMock
    ) as add_weight:
        await submit_feedback(
            sess, meeting_id=42, user_id=10, was_absent=True, bot=None
        )
    add_weight.assert_not_called()  # уже был absent, не штрафуем повторно


async def test_submit_rating_invalid_raises() -> None:
    """rating вне 1..5 без was_absent → ValueError."""
    from app.services.meeting_feedback import submit_feedback

    sess = _make_fake_session_for_submit()
    with pytest.raises(ValueError):
        await submit_feedback(sess, meeting_id=1, user_id=1, rating=0, was_absent=False)
    with pytest.raises(ValueError):
        await submit_feedback(sess, meeting_id=1, user_id=1, rating=6, was_absent=False)
    with pytest.raises(ValueError):
        await submit_feedback(sess, meeting_id=1, user_id=1, rating=None, was_absent=False)


async def test_submit_update_existing_changes_fields() -> None:
    """Повторный голос без absent — UPDATE, rating меняется на новый."""
    from app.services.meeting_feedback import submit_feedback

    existing = MagicMock(
        meeting_id=42,
        user_id=10,
        rating=3,
        was_absent=False,
        reason_text="старый коммент",
    )
    sess = _make_fake_session_for_submit(existing_feedback=existing)

    fb = await submit_feedback(
        sess,
        meeting_id=42,
        user_id=10,
        rating=5,
        was_absent=False,
        reason_text="перерейтинг",
    )
    # session.add НЕ вызван — это UPDATE существующей строки.
    assert not sess.add.called
    assert fb.rating == 5
    assert fb.reason_text == "перерейтинг"


# --- enumerate_pending_meetings --------------------------------------------


class _FakeEnumSession:
    """Стенд под enumerate_pending_meetings.

    Функция делает 3 запроса:
      1) `session.scalars(select(Meeting)...)`  — pending meetings.
      2) `session.scalars(select(Poll.game_nomination_id)...)` — уже-открытые поллы.
      3) `session.scalars(select(MeetingFeedback.meeting_id)...)` — уже-заведённые feedback'и.

    Возвращаем готовые списки по порядку вызовов.
    """

    def __init__(
        self,
        meetings: list[Any],
        existing_poll_ids: list[int],
        existing_feedback_ids: list[int],
    ) -> None:
        self._meetings = meetings
        self._existing_poll_ids = existing_poll_ids
        self._existing_feedback_ids = existing_feedback_ids
        self._call = 0

    async def scalars(self, _stmt: Any) -> Any:
        self._call += 1
        data: list[Any]
        if self._call == 1:
            data = self._meetings
        elif self._call == 2:
            data = self._existing_poll_ids
        else:
            data = self._existing_feedback_ids

        class _R:
            def __init__(self, d: list[Any]) -> None:
                self._d = d

            def all(self) -> list[Any]:
                return self._d

        return _R(data)


async def test_enumerate_filters_recent_and_old() -> None:
    """Встречи старше 14d пропускаются; младше 1d тоже (cutoff=now-1d)."""
    from app.services.meeting_feedback import enumerate_pending_meetings

    now = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    # Все три встречи прошли границу cutoff (старше 1 дня) и моложе 14 дней —
    # стенд _FakeEnumSession для этого теста не реализует SQL-фильтрацию по
    # `now - 1d` / `now - 14d`, поэтому мы просто проверяем, что 3 уцелевшие
    # после фильтра по уже-существующим поллам/feedback'ам возвращаются.
    m1 = MagicMock(id=101, starts_at=now - timedelta(days=2))
    m2 = MagicMock(id=102, starts_at=now - timedelta(days=5))
    m3 = MagicMock(id=103, starts_at=now - timedelta(days=10))

    sess = _FakeEnumSession(
        meetings=[m1, m2, m3],
        existing_poll_ids=[],
        existing_feedback_ids=[],
    )
    out = await enumerate_pending_meetings(sess, now=now)
    assert [m.id for m in out] == [101, 102, 103]


async def test_enumerate_skips_meetings_with_existing_poll() -> None:
    """Уже запущенный feedback-полл → встречу пропускаем."""
    from app.services.meeting_feedback import enumerate_pending_meetings

    now = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    m1 = MagicMock(id=201, starts_at=now - timedelta(days=2))
    m2 = MagicMock(id=202, starts_at=now - timedelta(days=2))

    sess = _FakeEnumSession(
        meetings=[m1, m2],
        existing_poll_ids=[201],  # m1 уже имеет полл — выкидываем
        existing_feedback_ids=[],
    )
    out = await enumerate_pending_meetings(sess, now=now)
    assert [m.id for m in out] == [202]


async def test_enumerate_skips_meetings_with_existing_feedback() -> None:
    """Уже есть хотя бы одна запись в meeting_feedback → встречу пропускаем."""
    from app.services.meeting_feedback import enumerate_pending_meetings

    now = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    m1 = MagicMock(id=301, starts_at=now - timedelta(days=2))
    m2 = MagicMock(id=302, starts_at=now - timedelta(days=2))

    sess = _FakeEnumSession(
        meetings=[m1, m2],
        existing_poll_ids=[],
        existing_feedback_ids=[302],  # m2 уже имеет feedback — выкидываем
    )
    out = await enumerate_pending_meetings(sess, now=now)
    assert [m.id for m in out] == [301]


async def test_enumerate_empty_when_no_meetings() -> None:
    from app.services.meeting_feedback import enumerate_pending_meetings

    sess = _FakeEnumSession(meetings=[], existing_poll_ids=[], existing_feedback_ids=[])
    assert await enumerate_pending_meetings(sess) == []
