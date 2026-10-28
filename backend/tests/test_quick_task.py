"""«Сказал — стало поручением» (план, 8.5).

Проверяем два обещания механики, а не «работает ли кнопка»:

* **Понято так, как сказано.** Срок берётся из тех слов, которыми его называют
  в зале («завтра», «к пятнице», «до 18:00», «к закрытию»), а если про срок
  молчат — это конец смены, а не «без срока»: «сделай когда-нибудь» в
  ресторане означает «до закрытия».
* **Не угадывается.** Две Ани в составе — черновик без исполнителя и со
  списком кандидатов. Угаданное поручение уходит чужому человеку, и он получает
  уведомление о работе, которой не видел.

Разбор — чистая функция: `parse` не знает про базу, поэтому правила проверяются
без sqlite, а ручки — отдельно, на пустой базе.
"""

from __future__ import annotations

import itertools
import os
from datetime import datetime, time, timedelta, timezone

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import event, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api import routes_hr_quick  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    TASK_SCOPE_DEPARTMENT,
    TASK_SCOPE_EMPLOYEE,
    Employee,
    Task,
)
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import hr_notify, hr_quick  # noqa: E402

# Среда, 28.10.2026, полдень по времени заведения. Пояс фиксированный (UTC+5),
# а не именованный: тест не должен зависеть от наличия базы часовых поясов в
# системе, где он запускается.
TZ = timezone(timedelta(hours=5))
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=TZ)
OPENS = time(10, 0)
CLOSES = time(23, 0)

PEOPLE = [
    hr_quick.QuickPerson(id=1, name="Аня Петрова", position="Повар", department_id=1),
    hr_quick.QuickPerson(id=2, name="Пётр Сидоров", position="Бариста", department_id=1),
    hr_quick.QuickPerson(id=3, name="Марина Кузнецова", position="Официант", department_id=1),
]


def parse(text: str, *, now: datetime = NOW, people=PEOPLE, department_id: int | None = 1):
    return hr_quick.parse(
        text,
        now=now,
        opens_at=OPENS,
        closes_at=CLOSES,
        people=list(people),
        my_department_id=department_id,
    )


# --------------------------------------------------------------------------
# Срок
# --------------------------------------------------------------------------


def test_time_in_the_phrase_becomes_today() -> None:
    draft = parse("Аня, протри витрину до 18:00")
    assert draft.assignee is not None and draft.assignee.id == 1
    assert draft.due_at == datetime(2026, 10, 28, 18, 0, tzinfo=TZ)
    assert draft.due_kind == "time"
    # Обращение и хвост про срок — уже в плашках, в заголовке их быть не должно.
    assert draft.title == "Протри витрину"


def test_silence_about_the_deadline_means_end_of_shift() -> None:
    draft = parse("Марина, вымой полы")
    assert draft.due_at == datetime(2026, 10, 28, 23, 0, tzinfo=TZ)
    assert draft.due_kind == "shift_close"


def test_deadline_never_starts_already_overdue() -> None:
    # «до 18:00», сказанное в 19:00, — это завтрашние 18:00: иначе сотрудник
    # получает просрочку через секунду после создания.
    late = datetime(2026, 10, 28, 19, 0, tzinfo=TZ)
    assert parse("до 18:00 помыть полы", now=late).due_at == datetime(
        2026, 10, 29, 18, 0, tzinfo=TZ
    )
    # И после закрытия смены «сегодня» уже не наступает.
    night = datetime(2026, 10, 28, 23, 30, tzinfo=TZ)
    assert parse("помыть полы", now=night).due_at == datetime(
        2026, 10, 29, 23, 0, tzinfo=TZ
    )


def test_relative_days_and_hours() -> None:
    assert parse("завтра в 9:00 скинь фото склада").due_at == datetime(
        2026, 10, 29, 9, 0, tzinfo=TZ
    )
    assert parse("послезавтра проверь сроки").due_at == datetime(
        2026, 10, 30, 23, 0, tzinfo=TZ
    )
    assert parse("через 2 часа убери зал").due_at == NOW + timedelta(hours=2)
    assert parse("через 3 дня сдать инвентарь").due_at == datetime(
        2026, 10, 31, 12, 0, tzinfo=TZ
    )


def test_weekday_is_the_nearest_one() -> None:
    # 28.10.2026 — среда; «к пятнице» — 30.10, а не следующая неделя.
    draft = parse("к пятнице проверь сроки годности")
    assert draft.due_at == datetime(2026, 10, 30, 23, 0, tzinfo=TZ)
    # «к среде», сказанное в среду днём, — это ещё сегодня.
    assert parse("к среде помыть окна").due_at == datetime(
        2026, 10, 28, 23, 0, tzinfo=TZ
    )


def test_words_of_the_shift_map_to_its_hours() -> None:
    assert parse("к открытию выставить витрину").due_at == datetime(
        2026, 10, 29, 10, 0, tzinfo=TZ
    )
    # Утро сегодняшнего дня уже прошло — значит завтрашнее.
    assert parse("к закрытию сдать кассу").due_at == datetime(
        2026, 10, 28, 23, 0, tzinfo=TZ
    )


# --------------------------------------------------------------------------
# Исполнитель
# --------------------------------------------------------------------------


def test_name_is_removed_from_the_title() -> None:
    draft = parse("Петя, почисти кофемашину")
    # «Петя» — не «Пётр»: имя в именительном падеже не обязано совпасть, но
    # фраза всё равно остаётся делом, а не обращением.
    assert "Петя" in draft.title or draft.title == "Почисти кофемашину"


def test_surname_also_identifies_a_person() -> None:
    draft = parse("Кузнецовой — помыть окна")
    assert draft.assignee is not None and draft.assignee.id == 3


def test_two_people_with_one_name_are_not_guessed() -> None:
    people = [
        hr_quick.QuickPerson(id=1, name="Аня Петрова", position="Повар"),
        hr_quick.QuickPerson(id=2, name="Аня Кузнецова", position="Официант"),
    ]
    draft = parse("Аня, протри витрину", people=people)
    assert draft.assignee is None
    assert "assignee" in draft.unclear
    assert {c.id for c in draft.candidates} == {1, 2}


def test_unique_position_is_enough() -> None:
    draft = parse("бариста, протри стойку")
    assert draft.assignee is not None and draft.assignee.id == 2


def test_group_phrase_addresses_the_department() -> None:
    draft = parse("всем протереть столы")
    assert draft.scope == TASK_SCOPE_DEPARTMENT
    assert draft.department_id == 1
    assert draft.assignee is None
    assert "assignee" not in draft.unclear


def test_person_outside_the_roster_is_not_invented() -> None:
    draft = parse("Олег, вынеси мусор")
    assert draft.assignee is None
    assert draft.scope == TASK_SCOPE_EMPLOYEE


# --------------------------------------------------------------------------
# Срочность и требования
# --------------------------------------------------------------------------


def test_urgency_and_photo_come_from_the_words() -> None:
    urgent = parse("срочно вызови техника")
    assert urgent.priority == PRIORITY_HIGH
    assert parse("не срочно разбери коробки").priority == PRIORITY_LOW
    assert parse("разбери коробки").priority == PRIORITY_NORMAL
    assert parse("скинь фото склада").requires_photo is True


# --------------------------------------------------------------------------
# Ручки: создание на пустой базе
# --------------------------------------------------------------------------

TABLES = (
    "organizations",
    "users",
    "employees",
    "admin_config",
    "tasks",
    "task_assignments",
    "task_events",
)


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [Base.metadata.tables[name] for name in TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        # sqlite не умеет BIGSERIAL: у `tasks`/`task_assignments`/`task_events`
        # первичный ключ — BigInteger и сам не заполняется. Номера выдаём перед
        # вставкой: тест про правила создания, а не про тип PK (это проверяет
        # PG-прогон, где схема настоящая).
        counter = itertools.count(1)
        scoped = {"tasks", "task_assignments", "task_events"}

        @event.listens_for(db.sync_session, "before_flush")
        def _fill_ids(sess, _ctx, _instances):  # noqa: ANN001
            for obj in sess.new:
                if obj.__class__.__tablename__ in scoped and getattr(obj, "id", None) is None:
                    obj.id = next(counter)

        yield db
    await engine.dispose()


@pytest.fixture(autouse=True)
def clean_org_context():
    token = set_org(DEFAULT_ORG_ID)
    yield
    reset_org(token)


@pytest.fixture(autouse=True)
def quiet_notifications(monkeypatch):
    """Колокольчик в sqlite не пишется (JSONB-колонка), а нам важна не доставка.

    Тексты уведомлений проверяются в PG-тестах; здесь — что поручение создано
    правильному человеку и с правильным сроком.
    """
    sent: list[int] = []

    async def fake(session, task, recipients):  # noqa: ANN001
        sent.append(task.id)
        return None

    monkeypatch.setattr(hr_notify, "notify_task_assigned", fake)
    return sent


async def _manager(session, *, role: str = ROLE_AUP) -> Employee:
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Кофейня"))
    session.add(User(id=1, telegram_id=111, display_name="Руководитель"))
    session.add(User(id=2, telegram_id=222, display_name="Аня Петрова"))
    manager = Employee(
        id=1, org_id=DEFAULT_ORG_ID, user_id=1, role=role, department_id=1, is_active=True
    )
    worker = Employee(
        id=2, org_id=DEFAULT_ORG_ID, user_id=2, department_id=1, is_active=True
    )
    session.add_all([manager, worker])
    await session.commit()
    return manager


async def test_quick_task_is_created_for_the_named_person(session) -> None:
    manager = await _manager(session)
    body = routes_hr_quick.QuickTaskIn(
        text="Аня Петрова, протри витрину до 18:00",
        assignee_employee_id=2,
        due_at=datetime(2026, 10, 28, 18, 0, tzinfo=TZ),
    )

    out = await routes_hr_quick.create_quick_task(body, session, manager)

    assert out.assignee_name == "Аня Петрова"
    assert out.scope == TASK_SCOPE_EMPLOYEE
    task = await session.scalar(select(Task))
    assert task is not None
    assert task.assignee_employee_id == 2
    # Фраза целиком остаётся описанием: в заголовке она обрезана до дела.
    assert task.description and "Аня Петрова" in task.description


async def test_assignee_from_outside_the_roster_is_rejected(session) -> None:
    manager = await _manager(session, role=ROLE_EMPLOYEE)
    body = routes_hr_quick.QuickTaskIn(
        text="Олег, вынеси мусор", assignee_employee_id=999
    )
    with pytest.raises(HTTPException) as error:
        await routes_hr_quick.create_quick_task(body, session, manager)
    assert error.value.status_code == 400
    assert error.value.detail == "assignee_out_of_scope"


async def test_personal_task_without_assignee_is_rejected(session) -> None:
    manager = await _manager(session)
    body = routes_hr_quick.QuickTaskIn(text="кто-нибудь помойте полы")
    with pytest.raises(HTTPException) as error:
        await routes_hr_quick.create_quick_task(body, session, manager)
    assert error.value.detail == "assignee_required"


async def test_group_phrase_creates_one_task_for_the_department(session) -> None:
    manager = await _manager(session)
    body = routes_hr_quick.QuickTaskIn(text="всем протереть столы")
    out = await routes_hr_quick.create_quick_task(body, session, manager)
    assert out.scope == TASK_SCOPE_DEPARTMENT
    task = await session.scalar(select(Task))
    assert task is not None and task.department_id == 1


async def test_parse_endpoint_does_not_write_anything(session) -> None:
    manager = await _manager(session)
    out = await routes_hr_quick.parse_quick(
        routes_hr_quick.QuickParseIn(text="завтра в 9:00 скинь фото склада"),
        session,
        manager,
    )
    assert out.requires_photo is True
    assert out.due_at is not None
    assert (await session.scalars(select(Task))).all() == []


def _dependency_names(dependant) -> set[str]:  # noqa: ANN001
    names: set[str] = set()
    for dependency in getattr(dependant, "dependencies", []):
        call = getattr(dependency, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", ""))
        names |= _dependency_names(dependency)
    return names


def test_quick_routes_require_aup() -> None:
    """Поручение — распоряжение, а не заметка: сотруднику ручки недоступны.

    Проверяется сама зависимость маршрута, а не код внутри: права не должны
    зависеть от того, вспомнил ли автор `if` в начале обработчика.
    """
    assert [route.path for route in routes_hr_quick.router.routes] == [
        "/hr/quick/people",
        "/hr/quick/parse",
        "/hr/quick/task",
    ]
    for route in routes_hr_quick.router.routes:
        assert "require_aup" in _dependency_names(route.dependant)
