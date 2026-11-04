"""Утренняя сводка руководителю (план, 8.2).

Проверяем то, что легко сломать незаметно:

* числа собираются из живых строк (просрочка, смены без чек-листа, прогоны в
  работе) и не считают тестовый пул;
* текст сообщения читается как человеческий: склонения, «всё спокойно» вместо
  пустого сообщения;
* повторный вызов в тот же день не присылает то же утро второй раз — иначе
  перезапуск планировщика превращается в спам.

Env выставляем до импорта настроек: `Settings` требует BOT_TOKEN и прочее.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db import models as _models  # noqa: E402,F401 — регистрирует `users`
from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    RUN_IN_PROGRESS,
    SHIFT_PLANNED,
    TASK_OVERDUE,
    ChecklistRun,
    Department,
    Employee,
    HrShift,
    Task,
)
from app.services import hr_digest, hr_settings, notify_prefs  # noqa: E402

TABLES = [
    # organizations/users нужны не для проверок, а для FK у `employees`.
    "organizations",
    "users",
    "departments",
    "halls",
    "employees",
    "tasks",
    "hr_shifts",
    "checklist_templates",
    "checklist_runs",
    "hr_issues",
    "admin_config",
    # 04.11.2026: персональные подписки на уведомления (0070). Без таблицы
    # сводка не могла проверить подписку и падала на `no such table`.
    "notify_prefs",
]

DAY = date(2026, 10, 27)


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [Base.metadata.tables[name] for name in TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _employee(
    session,
    *,
    employee_id: int,
    role: str = ROLE_EMPLOYEE,
    is_simulation: bool = False,
    telegram_id: int | None = None,
) -> Employee:
    employee = Employee(
        id=employee_id,
        user_id=employee_id,
        role=role,
        is_active=True,
        is_simulation=is_simulation,
    )
    session.add(employee)
    await session.flush()
    if telegram_id is not None:
        from app.db.models import User

        session.add(User(id=employee_id, telegram_id=telegram_id, display_name="Тест"))
        await session.flush()
    return employee


async def _subscribe(session, manager) -> None:
    """Включить сводку так, как это делает человек: глобально и лично.

    04.11.2026 обе подписки по умолчанию выключены — автоматическое сообщение в
    личку приходит только по явному выбору. Тест, который этого не делает,
    проверяет уже не отправку, а её отсутствие.
    """
    await hr_settings.set_digest_enabled(session, True)
    await notify_prefs.set_enabled(
        session,
        org_id=int(manager.org_id),
        user_id=int(manager.user_id),
        kind="digest",
        enabled=True,
    )
    await session.commit()


# --- Текст сообщения -------------------------------------------------------


def _digest(**overrides) -> hr_digest.Digest:
    base = {
        "day": DAY,
        "overdue_tasks": 0,
        "overdue_titles": (),
        "planned_today": 0,
        "not_started": 0,
        "open_runs": 0,
        "problems_open": 0,
        "problems_attention": 0,
    }
    base.update(overrides)
    return hr_digest.Digest(**base)


def test_calm_digest_is_stated_in_words_not_left_empty():
    text = hr_digest.message(_digest())
    assert "27.10" in text
    assert "Всё спокойно" in text


def test_message_declines_numbers_and_lists_titles():
    text = hr_digest.message(
        _digest(overdue_tasks=3, overdue_titles=("Проверить витрину", "Сдать смену"))
    )
    assert "Просрочено: 3 поручения" in text
    assert "Проверить витрину" in text


def test_message_uses_right_plural_for_one_and_five():
    assert "1 поручение" in hr_digest.message(
        _digest(overdue_tasks=1, overdue_titles=("Одно",))
    )
    assert "5 поручений" in hr_digest.message(_digest(overdue_tasks=5))
    # 11 — исключение из правила «1 → единственное».
    assert "11 поручений" in hr_digest.message(_digest(overdue_tasks=11))


def test_message_shows_missed_checklists_and_problems():
    text = hr_digest.message(
        _digest(not_started=2, planned_today=6, problems_open=4, problems_attention=1)
    )
    assert "Не открыли чек-лист: 2 смены из 6" in text
    assert "Открыто проблем: 4 проблемы, срочных: 1" in text


def test_message_puts_app_link_last():
    text = hr_digest.message(_digest(overdue_tasks=1), app_url="https://app.example")
    assert text.splitlines()[-1] == "https://app.example"


# --- Числа из базы ---------------------------------------------------------


async def test_build_counts_overdue_and_missing_checklists(session):
    manager = await _employee(session, employee_id=1, role=ROLE_AUP)
    first = await _employee(session, employee_id=2)
    second = await _employee(session, employee_id=3)

    session.add(
        Task(
            id=1,
            title="Проверить сроки",
            status=TASK_OVERDUE,
            due_at=datetime(2026, 10, 26, 12, 0),
            assignee_employee_id=first.id,
        )
    )
    session.add_all(
        [
            HrShift(id=1, employee_id=first.id, day=DAY, status=SHIFT_PLANNED),
            HrShift(id=2, employee_id=second.id, day=DAY, status=SHIFT_PLANNED),
        ]
    )
    # Один из двух открыл чек-лист — «не открыли» должен равняться одному.
    session.add(
        ChecklistRun(
            id=1,
            employee_id=first.id,
            template_id=1,
            shift_date=DAY,
            status=RUN_IN_PROGRESS,
        )
    )
    await session.commit()

    digest = await hr_digest.build(session, manager, today=DAY)

    assert digest.overdue_tasks == 1
    assert digest.overdue_titles == ("Проверить сроки",)
    assert digest.planned_today == 2
    assert digest.not_started == 1
    assert digest.open_runs == 1


async def test_build_ignores_simulation_pool(session):
    manager = await _employee(session, employee_id=1, role=ROLE_ADMIN)
    demo = await _employee(session, employee_id=2, is_simulation=True)
    session.add(HrShift(id=1, employee_id=demo.id, day=DAY, status=SHIFT_PLANNED))
    await session.commit()

    digest = await hr_digest.build(session, manager, today=DAY)

    # Тестовый пул не должен портить утреннюю картину: иначе сводку перестают
    # читать («там опять эти тестовые»).
    assert digest.planned_today == 0
    assert digest.not_started == 0
    assert digest.calm


# --- Отправка раз в сутки --------------------------------------------------


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.markups: list[object] = []

    async def send_message(self, *, chat_id: int, text: str, reply_markup=None) -> None:  # noqa: ANN001
        self.sent.append((chat_id, text))
        self.markups.append(reply_markup)


async def test_morning_digest_goes_out_once_per_day(session):
    manager = await _employee(
        session, employee_id=1, role=ROLE_AUP, telegram_id=555
    )
    assert manager.id == 1
    await _subscribe(session, manager)
    bot = FakeBot()

    first = await hr_digest.send_morning(session, bot=bot, app_url="https://app.example")
    second = await hr_digest.send_morning(session, bot=bot, app_url="https://app.example")

    assert first == 1
    assert second == 0
    assert len(bot.sent) == 1
    assert bot.sent[0][0] == 555
    # К каждому автоматическому сообщению крепятся кнопки: «выключить» сразу и
    # «настройки» (план 04.11.2026).
    markup = bot.markups[0]
    assert markup is not None
    assert "np:digest:off" in str(markup)
    assert "web_app" in str(markup)
    assert await hr_settings.get_digest_sent_on(session) == hr_digest.hr_settings.local_now().date()


async def test_force_allows_manual_resend(session):
    manager = await _employee(session, employee_id=1, role=ROLE_AUP, telegram_id=555)
    await _subscribe(session, manager)
    bot = FakeBot()

    await hr_digest.send_morning(session, bot=bot)
    # Ручная проверка из админки: «пришли ещё раз» — осознанное действие.
    await hr_digest.send_morning(session, bot=bot, force=True)

    assert len(bot.sent) == 2


async def test_no_opt_in_no_private_message(session):
    """Главное правило жалобы 04.11.2026: без личного «да» — ни одного сообщения.

    Глобальный тумблер организации включён, но человек своей подписки не
    ставил. Раньше сводка уходила всем руководителям — это и был спам.
    """
    manager = await _employee(session, employee_id=1, role=ROLE_AUP, telegram_id=555)
    await session.commit()
    await hr_settings.set_digest_enabled(session, True)
    bot = FakeBot()

    sent = await hr_digest.send_morning(session, bot=bot)

    assert sent == 0
    assert bot.sent == []
    assert await notify_prefs.get(
        session, org_id=int(manager.org_id), user_id=int(manager.user_id), kind="digest"
    ) is False


async def test_disabled_digest_sends_nothing(session):
    await _employee(session, employee_id=1, role=ROLE_AUP, telegram_id=555)
    await session.commit()
    await hr_settings.set_digest_enabled(session, False)
    bot = FakeBot()

    sent = await hr_digest.send_morning(session, bot=bot)

    assert sent == 0
    assert bot.sent == []
    # Отметка не выставляется: включив сводку обратно, человек получит её сразу.
    assert await hr_settings.get_digest_sent_on(session) is None
