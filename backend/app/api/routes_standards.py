"""REST API базы стандартов и проверки знаний.

Сотрудник читает инструкцию и сдаёт короткий тест; руководитель и админ
наполняют базу. Ключи правильных ответов наружу НЕ отдаются: фронт получает
вопросы без `correct_index`, а проверка идёт на сервере.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import EmployeeDep, SessionDep
from app.db.hr_models import (
    DEFAULT_PASS_PERCENT,
    STANDARD_CATEGORIES,
    Employee,
    Standard,
)
from app.services import hr_departments, hr_standards

router = APIRouter(tags=["standards"])


# --------------------------------------------------------------------------
# Схемы
# --------------------------------------------------------------------------


class QuestionOut(BaseModel):
    id: int
    text: str
    options: list[str]


class StandardOut(BaseModel):
    id: int
    title: str
    emoji: str | None
    category: str
    summary: str | None
    department_id: int | None
    department_name: str | None
    pass_percent: int
    # Обязательный стандарт попадает в пробелы отчёта смены.
    is_required: bool = False
    is_active: bool
    questions_count: int
    # Мой прогресс по этому стандарту.
    passed: bool
    last_percent: int | None


class StandardDetailOut(StandardOut):
    body: str
    questions: list[QuestionOut]


class StandardsOut(BaseModel):
    items: list[StandardOut]
    passed: int
    total: int
    attempts: int


class CheckIn(BaseModel):
    answers: list[int] = Field(min_length=1)


class CheckOut(BaseModel):
    standard_id: int
    total: int
    correct: int
    percent: int
    passed: bool
    pass_percent: int
    at: datetime
    # Разбор ошибок: индекс вопроса и правильный ответ (без текста «кто прав» —
    # человек сам вернётся к инструкции).
    wrong_indexes: list[int]


class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=2)
    correct_index: int = 0


class StandardIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    category: str = "other"
    emoji: str | None = Field(None, max_length=16)
    summary: str | None = None
    department_id: int | None = None
    pass_percent: int = DEFAULT_PASS_PERCENT
    is_required: bool = False
    sort_order: int = 0
    questions: list[QuestionIn] = []


# --------------------------------------------------------------------------
# Хелперы
# --------------------------------------------------------------------------


async def _dept_names(session: AsyncSession, ids: set[int]) -> dict[int, str]:
    names: dict[int, str] = {}
    for dep_id in ids:
        dept = await hr_departments.get_department(session, dep_id)
        if dept is not None:
            names[dep_id] = dept.name
    return names


async def _standard_out(
    session: AsyncSession,
    standard: Standard,
    *,
    employee: Employee,
    names: dict[int, str],
) -> StandardOut:
    questions = await hr_standards.questions_of(session, standard.id)
    attempt = await hr_standards.last_attempt(session, standard.id, employee.id)
    return StandardOut(
        id=standard.id,
        title=standard.title,
        emoji=standard.emoji,
        category=standard.category,
        summary=standard.summary,
        department_id=standard.department_id,
        department_name=names.get(standard.department_id or -1),
        pass_percent=standard.pass_percent,
        is_required=standard.is_required,
        is_active=standard.is_active,
        questions_count=len(questions),
        passed=bool(attempt and attempt.passed),
        last_percent=attempt.percent if attempt else None,
    )


# --------------------------------------------------------------------------
# Ручки сотрудника
# --------------------------------------------------------------------------


@router.get("/standards", response_model=StandardsOut)
async def list_standards(
    session: SessionDep, employee: EmployeeDep
) -> StandardsOut:
    rows = await hr_standards.list_standards(session, employee)
    names = await _dept_names(
        session, {s.department_id for s in rows if s.department_id}
    )
    stats = await hr_standards.summary_stats(session, employee)
    return StandardsOut(
        items=[
            await _standard_out(session, s, employee=employee, names=names)
            for s in rows
        ],
        passed=stats["passed"],
        total=stats["standards"],
        attempts=stats["attempts"],
    )


async def _visible_standard(
    session: AsyncSession, standard_id: int, employee: Employee
) -> Standard:
    standard = await hr_standards.get_standard(session, standard_id)
    # 404, а не 403: чужие стандарты не подтверждаем существованием.
    if standard is None or not hr_standards.can_view(employee, standard):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="standard_not_found")
    return standard


@router.get("/standards/{standard_id}", response_model=StandardDetailOut)
async def get_standard(
    standard_id: int, session: SessionDep, employee: EmployeeDep
) -> StandardDetailOut:
    standard = await _visible_standard(session, standard_id, employee)
    questions = await hr_standards.questions_of(session, standard.id)
    names = await _dept_names(
        session, {standard.department_id} if standard.department_id else set()
    )
    base = await _standard_out(session, standard, employee=employee, names=names)
    return StandardDetailOut(
        **base.model_dump(),
        body=standard.body,
        questions=[
            QuestionOut(id=q.id, text=q.text, options=list(q.options or []))
            for q in questions
        ],
    )


@router.post("/standards/{standard_id}/check", response_model=CheckOut)
async def submit_check(
    standard_id: int,
    body: CheckIn,
    session: SessionDep,
    employee: EmployeeDep,
) -> CheckOut:
    standard = await _visible_standard(session, standard_id, employee)
    questions = await hr_standards.questions_of(session, standard.id)
    try:
        check = await hr_standards.submit_check(
            session, standard, employee=employee, answers=body.answers
        )
    except hr_standards.StandardError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(check)

    wrong = [
        index
        for index, (question, given) in enumerate(zip(questions, body.answers, strict=False))
        if given != question.correct_index
    ]
    return CheckOut(
        standard_id=standard.id,
        total=check.total,
        correct=check.correct,
        percent=check.percent,
        passed=check.passed,
        pass_percent=standard.pass_percent,
        at=check.at,
        wrong_indexes=wrong,
    )


# --------------------------------------------------------------------------
# Наполнение базы (руководитель и админ)
# --------------------------------------------------------------------------


class AdminStandardOut(StandardOut):
    """То же плюс ключи ответов — только для того, кто базу наполняет."""

    questions: list[QuestionOut]
    correct_indexes: list[int]


class StandardPatch(BaseModel):
    """Точечная правка: обязательность и порог меняются чаще всего."""

    is_required: bool | None = None
    is_active: bool | None = None
    pass_percent: int | None = Field(
        None,
        ge=hr_standards.MIN_PASS_PERCENT,
        le=hr_standards.MAX_PASS_PERCENT,
    )


@router.patch(
    "/admin/standards/{standard_id}", response_model=StandardOut
)
async def patch_standard(
    standard_id: int,
    body: StandardPatch,
    session: SessionDep,
    employee: EmployeeDep,
) -> StandardOut:
    """Отметить стандарт обязательным (или снять) без переписывания текста."""
    from app.services import hr_access

    if not hr_access.is_aup(employee):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="aup_required")
    standard = await hr_standards.get_standard(session, standard_id)
    if standard is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="standard_not_found")

    await hr_standards.update_standard(
        session,
        standard,
        is_required=body.is_required,
        is_active=body.is_active,
        pass_percent=body.pass_percent,
    )
    await session.commit()
    await session.refresh(standard)

    names = await _dept_names(
        session, {standard.department_id} if standard.department_id else set()
    )
    return await _standard_out(session, standard, employee=employee, names=names)


@router.post(
    "/admin/standards", response_model=AdminStandardOut, status_code=201
)
async def create_standard(
    body: StandardIn,
    session: SessionDep,
    employee: EmployeeDep,
) -> AdminStandardOut:
    """Завести стандарт. Доступно руководителю и админу."""
    return await _create_standard(session, body, employee)


async def _create_standard(
    session: AsyncSession, body: StandardIn, employee: Employee
) -> AdminStandardOut:
    from app.services import hr_access

    if not hr_access.is_aup(employee):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="aup_required")
    if body.category not in STANDARD_CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_category")

    try:
        standard = await hr_standards.create_standard(
            session,
            title=body.title,
            body=body.body,
            category=body.category,
            emoji=body.emoji,
            summary=body.summary,
            department_id=body.department_id,
            pass_percent=body.pass_percent,
            is_required=body.is_required,
            sort_order=body.sort_order,
            questions=[
                (q.text, list(q.options), q.correct_index) for q in body.questions
            ],
        )
    except hr_standards.StandardError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(standard)

    questions = await hr_standards.questions_of(session, standard.id)
    names = await _dept_names(
        session, {standard.department_id} if standard.department_id else set()
    )
    base = await _standard_out(session, standard, employee=employee, names=names)
    return AdminStandardOut(
        **base.model_dump(),
        questions=[
            QuestionOut(id=q.id, text=q.text, options=list(q.options or []))
            for q in questions
        ],
        correct_indexes=[q.correct_index for q in questions],
    )
