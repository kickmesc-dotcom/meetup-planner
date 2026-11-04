"""Импорт людей и графика из CSV (B2B_PLATFORM_PLAN, шаг 6.3).

Проверяем не «файл разобрался», а обещания, которые даёт экран:

* предпросмотр ничего не пишет — иначе «проверить» уже меняло бы базу;
* ошибка в строке не отменяет остальные: двадцать из двадцати одного;
* повторный импорт не создаёт второго человека и второй смены;
* существующая смена не перезаписывается без явного `overwrite`;
* `;` и `,`, русские даты `21.10.2026` и статусы «больничный» понимаются;
* файл на 501 строку отклоняется целиком, а не половиной;
* ручки живут на `/api/import/*` — путь уже дважды разъезжался с фронтом.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import BigInteger, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # noqa: ARG001
    """Без этого `hr_shifts.id` в sqlite не автоинкрементится (BIGINT ≠ rowid).

    На проде BIGSERIAL, и вставка без id — норма; в тесте — тот же код должен
    работать, а не требовать явного id.
    """
    return "INTEGER"

from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ROLE_AUP,
    SHIFT_SICK,
    Department,
    Employee,
    HrShift,
)
from app.db.models import User  # noqa: E402
from app.services import people_import  # noqa: E402

TABLES = ("organizations", "users", "employees", "departments", "hr_shifts")

PEOPLE_CSV = (
    "имя;должность;подразделение;роль;telegram_id\n"
    "Анна Смирнова;Официант;Зал;сотрудник;\n"
    "Борис Петров;Повар;Кухня;сотрудник;\n"
    "Анна Смирнова;Дубль;Зал;сотрудник;\n"
)


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [Base.metadata.tables[name] for name in TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    # `set_org` здесь не нужен: у OrgScoped организация по умолчанию 1, а
    # `reset_org` из фикстуры падает — токен ContextVar создан в другом цикле.
    async with maker() as db:
        yield db
    await engine.dispose()


@pytest.fixture()
async def department(session):
    hall = Department(name="Зал", slug="hall", is_active=True, sort_order=0)
    session.add(hall)
    await session.commit()
    return hall


async def test_preview_reports_without_writing(session, department):
    result = await people_import.preview(session, text=PEOPLE_CSV)

    assert result.kind == "people"
    assert result.delimiter == ";"
    # Анна создаётся, Борис — нет подразделения, вторая Анна — дубль в файле.
    assert (result.create, result.skip, result.errors) == (1, 0, 2)
    # Главное: проверка ничего не записала.
    assert (await session.scalars(select(Employee))).all() == []


async def test_apply_creates_only_valid_rows(session, department):
    data = await people_import.apply(session, text=PEOPLE_CSV)

    assert (data["created"], data["errors"]) == (1, 2)
    employee = (await session.scalars(select(Employee))).one()
    user = await session.get(User, employee.user_id)
    assert user is not None and user.display_name == "Анна Смирнова"
    assert employee.department_id == department.id
    assert employee.role == "employee"


async def test_second_import_skips_existing_person(session, department):
    await people_import.apply(session, text=PEOPLE_CSV)
    again = await people_import.preview(session, text=PEOPLE_CSV)

    # Анна уже в пуле — «пропустить», а не второй профиль с тем же именем.
    assert again.create == 0
    assert again.skip == 1
    assert len((await session.scalars(select(Employee))).all()) == 1


async def test_shifts_understand_russian_dates_and_statuses(session, department):
    await people_import.apply(session, text=PEOPLE_CSV)
    shifts = (
        "имя;дата;статус;начало;конец\n"
        "Анна Смирнова;21.10.2026;больничный;;\n"
        "Неизвестный;21.10.2026;смена;10:00;18:00\n"
        "Анна Смирнова;32.13.2026;смена;;\n"
    )
    data = await people_import.apply(session, text=shifts)

    assert data["kind"] == "shifts"
    assert (data["created"], data["errors"]) == (1, 2)
    shift = (await session.scalars(select(HrShift))).one()
    assert shift.day == date(2026, 10, 21)
    assert shift.status == SHIFT_SICK
    assert shift.starts_at is None


async def test_existing_shift_needs_explicit_overwrite(session, department):
    await people_import.apply(session, text=PEOPLE_CSV)
    first = "имя;дата;статус\nАнна Смирнова;21.10.2026;смена\n"
    await people_import.apply(session, text=first)

    same = await people_import.preview(session, text=first)
    assert (same.create, same.update, same.skip) == (0, 0, 1)

    forced = "имя;дата;статус\nАнна Смирнова;21.10.2026;больничный\n"
    preview = await people_import.preview(session, text=forced, overwrite=True)
    assert (preview.update, preview.create) == (1, 0)

    data = await people_import.apply(session, text=forced, overwrite=True)
    assert (data["updated"], data["created"]) == (1, 0)
    shift = (await session.scalars(select(HrShift))).one()
    assert shift.status == SHIFT_SICK


async def test_comma_delimiter_and_roles(session, department):
    text = "name,position,department,role\nАнна,Официант,Зал,руководитель\n"
    preview = await people_import.preview(session, text=text)

    assert preview.delimiter == ","
    assert preview.create == 1
    data = await people_import.apply(session, text=text)
    assert data["created"] == 1
    employee = (await session.scalars(select(Employee))).one()
    assert employee.role == ROLE_AUP


async def test_too_many_rows_reject_the_file(session):
    header = "имя\n"
    body = "".join(f"Человек {index}\n" for index in range(people_import.MAX_ROWS + 1))
    with pytest.raises(people_import.ImportProblem) as caught:
        await people_import.preview(session, text=header + body)
    assert str(caught.value) == "too_many_rows"


async def test_missing_name_column_is_named(session):
    with pytest.raises(people_import.ImportProblem) as caught:
        await people_import.preview(session, text="что_то;другое\n1;2\n")
    assert str(caught.value) == "no_name_column"


async def test_empty_file_is_rejected(session):
    with pytest.raises(people_import.ImportProblem) as caught:
        await people_import.preview(session, text="   \n\n")
    assert str(caught.value) == "empty_file"


def test_routes_are_mounted_under_api():
    """Обход через `iter_route_objects`: в Starlette 1.x `app.routes` пуст."""
    from app.main import create_app
    from app.routing import iter_route_objects

    paths = {getattr(route, "path", "") for route in iter_route_objects(create_app())}
    assert "/api/import/preview" in paths
    assert "/api/import/apply" in paths
