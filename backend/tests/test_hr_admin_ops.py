"""Админские операции: чистые правила (без БД).

Здесь проверяем то, ради чего журнал вообще разделён на два вида: системные
строки планировщика (`auto_overdue`, `reminder_sent`) помечены флагом, а
человеческие действия читаются словами, а не техническими кодами статусов.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("ADMIN_TG_IDS", "")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from app.services import hr_admin_ops  # noqa: E402


def test_service_rows_are_marked_and_human_readable() -> None:
    text, system = hr_admin_ops.action_text("overdue", "auto_overdue")
    assert system is True
    assert "авто" in text

    text, system = hr_admin_ops.action_text("in_progress", "reminder_sent")
    assert system is True
    assert "напомнил" in text


def test_task_creation_keeps_mode_out_of_the_text() -> None:
    """`created:employee` — служебный маркер, в журнале его быть не должно."""
    text, system = hr_admin_ops.action_text("new", "created:employee")
    assert (text, system) == ("поставил(а) поручение", False)

    text, system = hr_admin_ops.action_text("new", "created:group")
    assert ":" not in text
    assert system is False


def test_human_statuses_are_translated() -> None:
    """Отметки исполнителя (`assignment:*`) — обычные человеческие действия."""
    for status, needle in (
        ("accepted", "принял"),
        ("done", "выполнил"),
        ("failed", "невыполненное"),
        ("on_review", "на проверку"),
    ):
        text, system = hr_admin_ops.action_text(status, "assignment:status")
        assert system is False
        assert needle in text


def test_unknown_status_does_not_leak_the_code() -> None:
    text, system = hr_admin_ops.action_text("nonsense", None)
    assert "nonsense" not in text
    assert system is False


def test_firing_modes_are_explicit() -> None:
    assert hr_admin_ops.FIRED_MODES == ("trash", "purge")
    assert hr_admin_ops.TRASH_DAYS == 30
