"""«Спасибо коллеге» (план, 8.4): правила, топ, лента и уведомление.

Проверяем не «работает ли кнопка», а четыре обещания механики:

* спасибо можно сказать только коллеге и только один раз в день — иначе топ
  набивается нажатиями и перестаёт что-либо значить;
* видно ровно свою область: сотрудник — себя, руководитель — своё
  подразделение, чужое не протекает через топ;
* запись попадает в ленту **обоим** — тому, кто сказал, и тому, кому сказали
  (иначе благодарность живёт только в колокольчике, который прочитают раз);
* тестовый пул в топ не попадает: «спасибо» боту обесценивает сам топ.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.hr_models import Employee, Kudos  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import hr_feed, hr_kudos, hr_notify  # noqa: E402

# `app_notifications` сюда не входит: у неё JSONB-колонка, которую sqlite не
# умеет (то же решение, что в `test_knowledge_search`). Запись в колокольчик
# проверяется подменой `notifications.add` — тексты и вид уведомления собирает
# наш код, а вставку строки в базу тестируют PG-тесты.
TABLES = (
    "organizations",
    "users",
    "employees",
    "admin_config",
    "hr_kudos",
)

DAY = date(2026, 10, 28)  # среда: неделя Пн 26.10 – вс 01.11


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


@pytest.fixture(autouse=True)
def clean_org_context():
    token = set_org(DEFAULT_ORG_ID)
    yield
    reset_org(token)


def _employee(
    employee_id: int,
    *,
    name: str,
    role: str = "employee",
    department_id: int | None = 1,
    telegram_id: int | None = None,
    **extra,
) -> tuple[User, Employee]:
    user = User(
        id=employee_id,
        telegram_id=telegram_id or 900000 + employee_id,
        display_name=name,
    )
    fields: dict = dict(role=role, department_id=department_id, is_active=True)
    fields.update(extra)
    employee = Employee(id=employee_id, user_id=employee_id, **fields)
    return user, employee


async def _seed(session, *rows) -> None:
    """Создать людей. Принимает и пары из `_employee`, и готовые профили."""
    # Организация одна на тест: `_seed` зовут и повторно, а повторная вставка
    # упала бы на дубле ключа и увела бы тест не туда.
    if await session.get(Organization, DEFAULT_ORG_ID) is None:
        session.add(
            Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя организация")
        )
    for row in rows:
        if isinstance(row, tuple):
            user, employee = row
            session.add(user)
            session.add(employee)
        else:
            session.add(row)
    await session.flush()


async def _worker(session) -> Employee:
    """Сотрудник + два коллеги в своём подразделении и один в чужом."""
    await _seed(
        session,
        _employee(1, name="Аня"),
        _employee(2, name="Борис"),
        _employee(3, name="Вера"),
        _employee(4, name="Гриша", department_id=2),
    )
    return await session.get(Employee, 1)


# --------------------------------------------------------------------------
# Правила
# --------------------------------------------------------------------------


async def test_self_kudos_rejected(session):
    me = await _worker(session)
    with pytest.raises(hr_kudos.KudosError) as exc:
        await hr_kudos.give(session, sender=me, to_employee_id=1, today=DAY)
    assert exc.value.code == hr_kudos.ERR_SELF


async def test_other_department_is_out_of_scope(session):
    me = await _worker(session)
    with pytest.raises(hr_kudos.KudosError) as exc:
        await hr_kudos.give(session, sender=me, to_employee_id=4, today=DAY)
    assert exc.value.code == hr_kudos.ERR_OUT_OF_SCOPE
    assert await session.scalar(select(Kudos.id)) is None


async def test_same_pair_twice_a_day_rejected(session):
    me = await _worker(session)
    await hr_kudos.give(session, sender=me, to_employee_id=2, today=DAY)
    await session.flush()
    with pytest.raises(hr_kudos.KudosError) as exc:
        await hr_kudos.give(session, sender=me, to_employee_id=2, today=DAY)
    assert exc.value.code == hr_kudos.ERR_ALREADY_TODAY


async def test_daily_limit_stops_flood(session):
    """Шестое спасибо за день — отказ, а не «ещё одна строка в топ»."""
    await _seed(
        session,
        *[_employee(i, name=f"Коллега {i}") for i in range(1, 9)],
    )
    me = await session.get(Employee, 1)
    for other in range(2, 2 + hr_kudos.MAX_PER_DAY):
        await hr_kudos.give(session, sender=me, to_employee_id=other, today=DAY)
    await session.flush()
    with pytest.raises(hr_kudos.KudosError) as exc:
        await hr_kudos.give(
            session,
            sender=me,
            to_employee_id=2 + hr_kudos.MAX_PER_DAY,
            today=DAY,
        )
    assert exc.value.code == hr_kudos.ERR_DAILY_LIMIT


async def test_long_message_rejected(session):
    me = await _worker(session)
    with pytest.raises(hr_kudos.KudosError) as exc:
        await hr_kudos.give(
            session,
            sender=me,
            to_employee_id=2,
            message="я" * (hr_kudos.MAX_MESSAGE + 1),
            today=DAY,
        )
    assert exc.value.code == hr_kudos.ERR_MESSAGE_TOO_LONG


async def test_next_day_allows_same_pair_again(session):
    """Лимит — на день, а не навсегда: завтра тому же человеку можно снова."""
    me = await _worker(session)
    await hr_kudos.give(session, sender=me, to_employee_id=2, today=DAY)
    await session.flush()
    await hr_kudos.give(
        session, sender=me, to_employee_id=2, today=DAY + timedelta(days=1)
    )
    await session.flush()
    assert await session.scalar(select(Kudos.id).order_by(Kudos.id.desc())) is not None


async def test_message_is_trimmed_and_empty_becomes_null(session):
    me = await _worker(session)
    row = await hr_kudos.give(
        session, sender=me, to_employee_id=2, message="  спасибо за подмену  ", today=DAY
    )
    await session.flush()
    assert row.message == "спасибо за подмену"

    empty = await hr_kudos.give(
        session, sender=me, to_employee_id=3, message="   ", today=DAY
    )
    await session.flush()
    assert empty.message is None


async def test_thankable_excludes_self_and_other_department(session):
    me = await _worker(session)
    ids = await hr_kudos.thankable_ids(session, me)
    assert ids == {2, 3}


async def test_thankable_excludes_fired(session):
    await _seed(
        session,
        _employee(1, name="Аня"),
        _employee(2, name="Борис", is_active=False),
    )

    me = await session.get(Employee, 1)
    assert await hr_kudos.thankable_ids(session, me) == set()


async def test_manager_can_thank_across_departments(session):
    """Управляющий видит всех — правило области его не сужает."""
    admin = _employee(1, name="Управляющий", role="admin", department_id=None)
    await _seed(session, admin, _employee(4, name="Гриша", department_id=2))
    me = await session.get(Employee, 1)
    assert await hr_kudos.thankable_ids(session, me) == {4}


# --------------------------------------------------------------------------
# Недельный топ
# --------------------------------------------------------------------------


async def test_weekly_top_counts_and_place(session):
    """Топ руководителя: своё подразделение, по убыванию, с местом смотрящего."""
    await _seed(
        session,
        _employee(1, name="Руководитель", role="aup"),
        _employee(2, name="Борис"),
        _employee(3, name="Вера"),
        _employee(5, name="Даша"),
    )
    sender_2 = await session.get(Employee, 2)
    sender_3 = await session.get(Employee, 3)
    sender_5 = await session.get(Employee, 5)
    await hr_kudos.give(session, sender=sender_3, to_employee_id=2, today=DAY)
    await hr_kudos.give(session, sender=sender_5, to_employee_id=2, today=DAY)
    await hr_kudos.give(session, sender=sender_2, to_employee_id=3, today=DAY)
    await session.flush()

    aup = await session.get(Employee, 1)
    week = await hr_kudos.weekly(session, aup, today=DAY)
    assert week.since == date(2026, 10, 26)
    assert week.until == date(2026, 11, 1)
    assert [(row.employee_id, row.count) for row in week.top] == [(2, 2), (3, 1)]
    # Руководитель сам ничего не получал и никого не благодарил — места в топе
    # у него нет, и это не ошибка.
    assert week.my_place is None
    assert week.received == 0
    assert week.given == 0


async def test_employee_top_is_only_own_row(session):
    """Сотрудник видит в топе только себя: имена коллег — не обход ленты.

    Это сознательное правило, а не недоработка: лента сотрудника — только его
    действия, и топ не должен становиться дырой в том же правиле. Свои числа
    при этом видны полностью.
    """
    ia = await _worker(session)  # Аня, сотрудник подразделения 1
    await _seed(session, _employee(5, name="Даша"))
    await session.flush()
    sender_2 = await session.get(Employee, 2)
    sender_5 = await session.get(Employee, 5)
    # Борис получает два спасибо и сам благодарит Веру.
    await hr_kudos.give(session, sender=sender_5, to_employee_id=2, today=DAY)
    await hr_kudos.give(session, sender=sender_2, to_employee_id=3, today=DAY)
    await session.flush()

    week = await hr_kudos.weekly(session, ia, today=DAY)
    assert week.top == []
    assert week.my_place is None


async def test_employee_sees_only_own_row(session):
    """Топ не становится способом узнать чужие имена в обход видимости."""
    me = await _worker(session)
    await session.flush()
    colleague = await session.get(Employee, 2)
    await hr_kudos.give(session, sender=colleague, to_employee_id=3, today=DAY)
    await session.flush()

    week = await hr_kudos.weekly(session, me, today=DAY)
    # Аня ничего не получала и никому не говорила: топ пуст, места нет.
    assert week.top == []
    assert week.my_place is None
    assert week.received == 0
    assert week.given == 0


async def test_manager_top_is_limited_to_own_department(session):
    await _seed(
        session,
        _employee(1, name="Руководитель", role="aup"),
        _employee(2, name="Борис"),
        _employee(4, name="Гриша", department_id=2),
        _employee(5, name="Даша", department_id=2),
    )
    grisha = await session.get(Employee, 4)
    dasha = await session.get(Employee, 5)
    # Спасибо внутри чужого подразделения.
    await hr_kudos.give(session, sender=dasha, to_employee_id=4, today=DAY)
    await session.flush()

    aup = await session.get(Employee, 1)
    week = await hr_kudos.weekly(session, aup, today=DAY)
    assert [row.employee_id for row in week.top] == []
    assert week.my_place is None


async def test_today_left_decreases_and_never_negative(session):
    me = await _worker(session)
    before = await hr_kudos.weekly(session, me, today=DAY)
    assert before.today_left == hr_kudos.MAX_PER_DAY

    await hr_kudos.give(session, sender=me, to_employee_id=2, today=DAY)
    await session.flush()
    after = await hr_kudos.weekly(session, me, today=DAY)
    assert after.today_left == hr_kudos.MAX_PER_DAY - 1


async def test_previous_week_does_not_count(session):
    me = await _worker(session)
    colleague = await session.get(Employee, 2)
    await session.flush()
    await hr_kudos.give(
        session,
        sender=me,
        to_employee_id=2,
        today=DAY - timedelta(days=7),
    )
    await session.flush()
    week = await hr_kudos.weekly(session, colleague, today=DAY)
    assert week.received == 0


async def test_simulation_pool_not_in_top(session):
    """Теневой профиль и тестовый пул топ не занимают."""
    await _seed(
        session,
        _employee(1, name="Аня"),
        _employee(2, name="Борис", is_simulation=True),
        _employee(3, name="Вера", is_demo=True),
    )
    me = await session.get(Employee, 1)
    session.add_all(
        [
            Kudos(
                from_employee_id=1,
                to_employee_id=2,
                day=DAY,
                created_at=datetime(2026, 10, 28, 9, 0),
            ),
            Kudos(
                from_employee_id=1,
                to_employee_id=3,
                day=DAY,
                created_at=datetime(2026, 10, 28, 10, 0),
            ),
        ]
    )
    await session.flush()

    week = await hr_kudos.weekly(session, me, today=DAY)
    assert week.top == []


# --------------------------------------------------------------------------
# Лента и уведомление
# --------------------------------------------------------------------------


async def test_kudos_appears_in_both_feeds(session):
    me = await _worker(session)
    colleague = await session.get(Employee, 2)
    await hr_kudos.give(
        session,
        sender=me,
        to_employee_id=2,
        message="спасибо за подмену",
        today=DAY,
    )
    await session.flush()

    mine = await hr_feed.build_feed(session, me, kinds=("kudos",))
    theirs = await hr_feed.build_feed(session, colleague, kinds=("kudos",))
    assert [item.kind for item in mine] == ["kudos"]
    assert "спасибо за подмену" in mine[0].text
    # Получивший благодарность тоже должен найти её в своей ленте.
    assert [item.kind for item in theirs] == ["kudos"]
    assert theirs[0].employee_id == 1


async def test_kudos_feed_text_speaks_english(session):
    me = await _worker(session)
    await hr_kudos.give(
        session, sender=me, to_employee_id=2, message="for the shift", today=DAY
    )
    await session.flush()
    items = await hr_feed.build_feed(session, me, kinds=("kudos",), lang="en")
    assert items[0].text == "thanked Борис: “for the shift”"


async def test_kudos_kind_is_available_in_feed_filters(session):
    assert hr_feed.KIND_KUDOS in hr_feed.ALL_KINDS


async def test_notification_goes_to_recipient(session, monkeypatch):
    """Благодарность не просто появляется в ленте — о ней сообщают адресату."""
    calls: list[dict] = []

    async def _capture(_session, *, user_id, kind, text, payload=None):
        calls.append({"user_id": user_id, "kind": kind, "text": text, "payload": payload})

    monkeypatch.setattr(hr_notify.notifications, "add", _capture)

    colleague = _employee(2, name="Борис")[1]
    await _seed(session, _employee(1, name="Аня"), colleague)
    await session.flush()
    await hr_notify.notify_kudos(
        session,
        await session.get(Employee, 2),
        from_name="Аня",
        message="спасибо за подмену",
    )

    assert len(calls) == 1
    assert calls[0]["user_id"] == colleague.user_id
    assert calls[0]["kind"] == hr_notify.KIND_KUDOS
    assert "Аня" in calls[0]["text"]
    assert "спасибо за подмену" in calls[0]["text"]


async def test_notification_without_message_still_reads(session):
    """Записи может не быть — механика не должна требовать объяснения."""
    text = hr_notify.kudos_text(from_name="Аня", message=None)
    assert "Аня" in text
    assert "«" not in text


# --------------------------------------------------------------------------
# Ручки: коды ошибок и ответ одним запросом
# --------------------------------------------------------------------------


async def test_route_translates_rule_to_code(session, monkeypatch):
    """Отказ приходит кодом, а не текстом: интерфейс сам переводит его."""
    from fastapi import HTTPException

    from app.api import routes_hr

    me = await _worker(session)
    with pytest.raises(HTTPException) as exc:
        await routes_hr.give_kudos(
            routes_hr.KudosIn(to_employee_id=1), session, await session.get(User, 1), me
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == hr_kudos.ERR_SELF


async def test_route_answers_with_the_whole_week(session, monkeypatch):
    """Один запрос — и на экране уже новое число: без второго захода за топом."""
    from unittest.mock import AsyncMock

    from app.api import routes_hr

    monkeypatch.setattr(hr_notify, "notify_kudos", AsyncMock())
    me = await _worker(session)
    out = await routes_hr.give_kudos(
        routes_hr.KudosIn(to_employee_id=2, message="спасибо за подмену"),
        session,
        await session.get(User, 1),
        me,
    )
    assert out.given == 1
    assert out.received == 0
    assert out.today_left == hr_kudos.MAX_PER_DAY - 1
    assert out.can_thank == 2


async def test_route_people_lists_colleagues(session):
    from app.api import routes_hr

    me = await _worker(session)
    people = await routes_hr.kudos_people(session, me)
    assert [person.display_name for person in people] == ["Борис", "Вера"]
