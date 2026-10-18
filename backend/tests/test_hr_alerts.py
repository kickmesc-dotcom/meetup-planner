"""Правила кнопок под алертами: парсинг, «заглушено ли», отложка до утра.

Тесты без базы: всё, что можно проверить как решение по данным, вынесено в
чистые функции `services/hr_alerts.py`. Именно эти правила решают, разбудит ли
бот управляющего повторно.
"""

from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services import hr_alerts

MSK = ZoneInfo("Europe/Moscow")


def _task(task_id: int):
    return SimpleNamespace(id=task_id, status="overdue")


# --- Разбор callback-данных -------------------------------------------------


def test_parse_actions():
    assert hr_alerts.parse_callback(hr_alerts.cb_resolve(7)) == hr_alerts.Action(
        action="resolve", task_id=7
    )
    assert hr_alerts.parse_callback(hr_alerts.cb_tomorrow(7)) == hr_alerts.Action(
        action="tomorrow", task_id=7
    )
    assert hr_alerts.parse_callback(hr_alerts.cb_mute(72)) == hr_alerts.Action(
        action="mute", hours=72
    )


def test_parse_rejects_foreign_and_broken_data():
    for data in (
        None,
        "",
        "hr:dept:1",
        "hra",
        "hra:resolve",
        "hra:resolve:abc",
        "hra:mute:5",  # такой длительности в меню нет — значит кнопка подделана
        "hra:unknown:1",
    ):
        assert hr_alerts.parse_callback(data) is None, data


def test_mute_choices_are_offered_in_keyboard():
    keyboard = hr_alerts.alert_keyboard(11)
    rows = keyboard.inline_keyboard
    assert len(rows) == 3
    assert rows[0][0].callback_data == hr_alerts.cb_resolve(11)
    assert rows[1][0].callback_data == hr_alerts.cb_tomorrow(11)
    mute_data = [button.callback_data for button in rows[2]]
    assert mute_data == [
        hr_alerts.cb_mute(hours) for _label, hours in hr_alerts.MUTE_CHOICES
    ]
    assert "24 ч" in rows[2][0].text


# --- Состояние: решено / отложено ------------------------------------------


def test_resolved_wins_over_snooze():
    state = hr_alerts.state_from_comments(
        ["alert_snooze:2999-01-01T00:00:00+00:00", hr_alerts.COMMENT_RESOLVED]
    )
    assert state.resolved is True
    assert state.silenced(datetime(2026, 10, 18, tzinfo=UTC)) is True


def test_snooze_silences_until_moment_and_lets_alerts_back():
    until = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)
    state = hr_alerts.state_from_comments([hr_alerts.snooze_comment(until)])
    assert state.silenced(datetime(2026, 10, 18, 23, 0, tzinfo=UTC)) is True
    assert state.silenced(until + timedelta(minutes=1)) is False


def test_latest_snooze_wins_and_garbage_is_ignored():
    early = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)
    late = datetime(2026, 10, 25, 7, 0, tzinfo=UTC)
    state = hr_alerts.state_from_comments(
        [hr_alerts.snooze_comment(late), "alert_snooze:мусор", hr_alerts.snooze_comment(early)]
    )
    assert state.snoozed_until == late
    assert hr_alerts.parse_snooze("напоминание отправлено") is None
    assert hr_alerts.parse_snooze(None) is None


def test_clean_task_is_not_silenced():
    state = hr_alerts.state_from_comments(["reminder_sent"])
    assert state.silenced(datetime(2026, 10, 18, tzinfo=UTC)) is False


def test_filter_silenced_keeps_only_active_tasks():
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    tasks = [_task(1), _task(2), _task(3)]
    state_map = {
        2: hr_alerts.AlertState(resolved=True),
        3: hr_alerts.AlertState(snoozed_until=now + timedelta(hours=5)),
    }
    assert [t.id for t in hr_alerts.filter_silenced(tasks, state_map, now)] == [1]
    # Спустя сутки отложенное поручение снова получает алерт.
    later = now + timedelta(days=1)
    assert [t.id for t in hr_alerts.filter_silenced(tasks, state_map, later)] == [1, 3]


# --- «Напомнить завтра» -----------------------------------------------------


def test_next_shift_morning_is_tomorrow_at_opening_time():
    now = datetime(2026, 10, 18, 3, 41, tzinfo=MSK)  # тот самый ночной алерт
    until = hr_alerts.next_shift_morning(now, opens_at=time(9, 30), tz=MSK)
    assert until == datetime(2026, 10, 19, 9, 30, tzinfo=MSK)
    assert until.astimezone(UTC) > now.astimezone(UTC)


def test_next_shift_morning_from_evening_goes_to_next_day():
    now = datetime(2026, 10, 18, 23, 50, tzinfo=MSK)
    until = hr_alerts.next_shift_morning(now, opens_at=time(10, 0), tz=MSK)
    assert until.date() == datetime(2026, 10, 19).date()
