"""Дата смены для отметки из офлайн-очереди.

Отметку поставили в подвале без сети, а отправили через час (или утром).
Сервер не должен писать её в «сегодня»: иначе вечерняя смена закрывается
утренним прогоном, а отчёт за прошлый день навсегда остаётся пустым.

Граница — неделя. Очередь — страховка от обрыва, а не способ задним числом
поправить закрытый отчёт; всё, что старше, отклоняется до записи.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402

from app.services import hr_checklists  # noqa: E402

TODAY = date(2026, 11, 5)


def test_without_date_uses_today() -> None:
    assert hr_checklists.resolve_shift_date(None, TODAY) == TODAY


def test_yesterday_is_allowed() -> None:
    assert hr_checklists.resolve_shift_date(TODAY - timedelta(days=1), TODAY) == (
        TODAY - timedelta(days=1)
    )


def test_a_week_ago_is_still_allowed() -> None:
    week_ago = TODAY - timedelta(days=hr_checklists.OFFLINE_MAX_DAYS)
    assert hr_checklists.resolve_shift_date(week_ago, TODAY) == week_ago


@pytest.mark.parametrize(
    "requested",
    [
        TODAY + timedelta(days=1),
        TODAY - timedelta(days=hr_checklists.OFFLINE_MAX_DAYS + 1),
        TODAY - timedelta(days=90),
    ],
)
def test_future_and_old_are_rejected(requested: date) -> None:
    with pytest.raises(hr_checklists.ChecklistError) as exc:
        hr_checklists.resolve_shift_date(requested, TODAY)
    assert str(exc.value) == "bad_shift_date"
