"""Публичный API организации `/api/v1` (B2B_PLATFORM_PLAN, шаг 6.1).

Зачем отдельный префикс `/api/v1`, а не те же ручки. У интегратора должен быть
контракт, который не меняется вместе с интерфейсом: `v1` — это обещание, что
поля и смысл ответов останутся, даже когда экраны в приложении переедут.
Внутренние ручки живут на `/api/hr/...` и меняются свободно.

Почему ключ в заголовке, а не в query. Ключ в адресе попадает в логи прокси и
в историю браузера; `X-Api-Key` — единственное место, откуда мы его читаем, и
в логи он не пишется.

Почему только чтение. Запись через публичный API — это второй путь создания
данных, который обязан повторить все проверки ролей и лимитов кабинета. Пока
интегратору нужен обмен «люди и график», честный read-only API закрывает
задачу целиком; запись появится, когда будет понятен спрос.

Почему контакты отдельным правом. Почта — персональные данные, и интегратору
для расстановки смен хватает имени и должности. Отдаём контакты только ключу со
scope `contacts.read`: это видно в кабинете и отзывается отдельно.
"""

from __future__ import annotations

from datetime import date, datetime

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ApiKeyDep, SessionDep
from app.api.routes_import import (
    PROBLEM_TEXT,
    ImportIn,
    ImportPreviewOut,
    ImportResultOut,
)
from app.db.hr_models import Department, Employee, HrShift, MenuItem
from app.db.models import User
from app.db.org_models import Organization
from app.services import api_ingest, api_keys, people_import

router = APIRouter(prefix="/v1", tags=["public-api"])

# Предел выборки: интегратору нужны страницы, а не «вся база одним ответом».
MAX_LIMIT = 200
# Горизонт графика. Квартал — рабочий горизонт планирования; больше похоже на
# выгрузку базы, а для выгрузки есть `/api/org/export` в кабинете.
MAX_SHIFT_DAYS = 92


class MeOut(BaseModel):
    """Кто я и что мне можно — первая ручка интегратора при настройке."""

    org_id: int
    org_slug: str
    org_name: str
    key_name: str
    scopes: list[str]


class DepartmentOut(BaseModel):
    id: int
    name: str
    slug: str
    emoji: str | None
    is_active: bool


class EmployeeOut(BaseModel):
    id: int
    name: str
    position: str | None
    badge: str | None
    department_id: int | None
    is_active: bool
    hired_at: date | None
    email: str | None = None


class ShiftOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    day: date
    status: str
    starts_at: str | None
    ends_at: str | None


class MenuItemOut(BaseModel):
    id: int
    category: str | None
    name: str
    price_rub: int | None
    is_available: bool


def _require(key, scope: str) -> None:
    if not api_keys.has_scope(key, scope):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"scope_required:{scope}")


def _limit(value: int) -> int:
    return max(1, min(int(value), MAX_LIMIT))


@router.get("/me", response_model=MeOut)
async def whoami(session: SessionDep, key: ApiKeyDep) -> MeOut:
    org = await session.get(Organization, key.org_id)
    if org is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="org_missing")
    return MeOut(
        org_id=org.id,
        org_slug=org.slug,
        org_name=org.name,
        key_name=key.name,
        scopes=list(api_keys.scopes_of(key)),
    )


@router.get("/departments", response_model=list[DepartmentOut])
async def departments(
    session: SessionDep, key: ApiKeyDep, include_inactive: bool = False
) -> list[DepartmentOut]:
    _require(key, "people.read")
    query = select(Department).order_by(Department.sort_order, Department.id)
    if not include_inactive:
        query = query.where(Department.is_active.is_(True))
    rows = await session.scalars(query)
    return [
        DepartmentOut(
            id=row.id,
            name=row.name,
            slug=row.slug,
            emoji=row.emoji,
            is_active=row.is_active,
        )
        for row in rows
    ]


async def _employee_rows(
    session: AsyncSession, *, include_inactive: bool, limit: int, offset: int
) -> list[tuple[Employee, User]]:
    query = (
        select(Employee, User)
        .join(User, User.id == Employee.user_id)
        .order_by(Employee.id)
        .limit(limit)
        .offset(offset)
    )
    if not include_inactive:
        query = query.where(Employee.is_active.is_(True))
    rows = await session.execute(query)
    return [(employee, user) for employee, user in rows.all()]


@router.get("/employees", response_model=list[EmployeeOut])
async def employees(
    session: SessionDep,
    key: ApiKeyDep,
    include_inactive: bool = False,
    limit: int = Query(default=100, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> list[EmployeeOut]:
    """Люди организации. Контакты — только ключу с правом `contacts.read`."""
    _require(key, "people.read")
    with_contacts = api_keys.has_scope(key, "contacts.read")
    rows = await _employee_rows(
        session,
        include_inactive=include_inactive,
        limit=_limit(limit),
        offset=offset,
    )
    return [
        EmployeeOut(
            id=employee.id,
            name=user.display_name or "",
            position=employee.position,
            badge=employee.badge,
            department_id=employee.department_id,
            is_active=employee.is_active,
            hired_at=employee.hire_date,
            email=(user.email if with_contacts else None),
        )
        for employee, user in rows
    ]


@router.get("/shifts", response_model=list[ShiftOut])
async def shifts(
    session: SessionDep,
    key: ApiKeyDep,
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
) -> list[ShiftOut]:
    """График за период. Пустая ячейка отсутствует, а не приходит null-днём."""
    _require(key, "schedule.read")
    if date_to < date_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="range_invalid")
    if (date_to - date_from).days > MAX_SHIFT_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="range_too_long")
    rows = await session.execute(
        select(HrShift, Employee, User)
        .join(Employee, Employee.id == HrShift.employee_id)
        .join(User, User.id == Employee.user_id)
        .where(HrShift.day >= date_from, HrShift.day <= date_to)
        .order_by(HrShift.day, HrShift.id)
    )
    return [
        ShiftOut(
            id=shift.id,
            employee_id=shift.employee_id,
            employee_name=user.display_name or "",
            day=shift.day,
            status=shift.status,
            starts_at=shift.starts_at.strftime("%H:%M") if shift.starts_at else None,
            ends_at=shift.ends_at.strftime("%H:%M") if shift.ends_at else None,
        )
        for shift, _employee, user in rows.all()
    ]


@router.get("/menu", response_model=list[MenuItemOut])
async def menu(session: SessionDep, key: ApiKeyDep) -> list[MenuItemOut]:
    _require(key, "menu.read")
    rows = await session.scalars(
        select(MenuItem).order_by(MenuItem.category, MenuItem.sort_order, MenuItem.id)
    )
    return [
        MenuItemOut(
            id=row.id,
            category=row.category,
            name=row.name,
            price_rub=row.price_rub,
            is_available=row.is_available,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Входящий обмен (шаг 6.2)
#
# Зачем запись в публичном API, если шаг 6.1 был намеренно read-only. Там
# запись означала «второй путь создания данных без проверок кабинета». Здесь
# путь один и тот же: `people_import` — тот же разбор, что у экрана импорта,
# а права проверяются по виду данных и **до** записи. 1С и Excel не ждут
# подписания контракта с вендором: они умеют отдать CSV.
# ---------------------------------------------------------------------------


class ImportRunOut(BaseModel):
    """Строка журнала входящих импортов: числа и имя файла, без тела ответа."""

    id: int
    key_id: int
    kind: str
    filename: str | None
    status: str
    created: int
    updated: int
    skipped: int
    errors: int
    idempotency_key: str | None
    created_at: datetime


def _import_problem(exc: people_import.ImportProblem) -> HTTPException:
    code = str(exc)
    return HTTPException(
        status.HTTP_400_BAD_REQUEST,
        detail=code if code in PROBLEM_TEXT else "import_failed",
    )


def _ingest_problem(exc: api_ingest.ApiIngestError) -> HTTPException:
    code = str(exc)
    if code.startswith("scope_required:"):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=code)
    if code == "idempotency_key_reused":
        # Тот же ключ идемпотентности с другим файлом — ошибка интегратора.
        # Вернуть сохранённый ответ значило бы соврать «данные применены».
        return HTTPException(status.HTTP_409_CONFLICT, detail=code)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=code)


@router.post("/import/preview", response_model=ImportPreviewOut)
async def api_import_preview(
    payload: ImportIn, session: SessionDep, key: ApiKeyDep
) -> ImportPreviewOut:
    """Разбор без записи. Право на вид данных проверяется до ответа."""
    try:
        data = await api_ingest.preview(
            session,
            key=key,
            text=payload.text,
            kind=payload.kind,
            overwrite=payload.overwrite,
        )
    except people_import.ImportProblem as exc:
        raise _import_problem(exc) from exc
    except api_ingest.ApiIngestError as exc:
        raise _ingest_problem(exc) from exc
    return ImportPreviewOut(**data)


@router.post("/import/apply", response_model=ImportResultOut)
async def api_import_apply(
    payload: ImportIn,
    session: SessionDep,
    key: ApiKeyDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ImportResultOut:
    """Применить разбор. Повтор с тем же `Idempotency-Key` — тот же ответ."""
    try:
        data, _replay = await api_ingest.apply(
            session,
            key=key,
            text=payload.text,
            kind=payload.kind,
            overwrite=payload.overwrite,
            filename=payload.filename,
            idempotency_key=idempotency_key,
        )
    except people_import.ImportProblem as exc:
        raise _import_problem(exc) from exc
    except api_ingest.ApiIngestError as exc:
        raise _ingest_problem(exc) from exc
    return ImportResultOut(**data)


@router.get("/import/runs", response_model=list[ImportRunOut])
async def api_import_runs(
    session: SessionDep,
    key: ApiKeyDep,
    limit: int = Query(default=20, ge=1, le=api_ingest.MAX_RUNS),
) -> list[ImportRunOut]:
    """Журнал прогонов: «ошибки видны» — это числа и файл, а не только код 200."""
    rows = await api_ingest.runs(session, key.org_id, limit=limit)
    return [
        ImportRunOut(
            id=row.id,
            key_id=row.key_id,
            kind=row.kind,
            filename=row.filename,
            status=row.status,
            created=row.created,
            updated=row.updated,
            skipped=row.skipped,
            errors=row.errors,
            idempotency_key=row.idempotency_key,
            created_at=row.created_at,
        )
        for row in rows
    ]


__all__ = ["MAX_LIMIT", "MAX_SHIFT_DAYS", "router"]
