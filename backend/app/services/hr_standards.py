"""База стандартов и проверка знаний.

Что здесь есть кроме CRUD: правило сдачи. Оно вынесено в чистую функцию
`grade`, потому что от него зависит, откроется ли человеку смена: ошибка в
подсчёте — это либо допущенный к работе новичок, либо несправедливый «не сдал».
Поэтому же результат пишется историей (`standard_checks`), а не полем на
сотруднике: пересдача не стирает предыдущую попытку.

Видимость: стандарт без подразделения — общий, с подразделением — только этому
подразделению. Сотрудник без отдела видит общие.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    DEFAULT_PASS_PERCENT,
    STANDARD_CATEGORIES,
    Employee,
    Standard,
    StandardCheck,
    StandardQuestion,
)

log = structlog.get_logger()

MIN_PASS_PERCENT = 50
MAX_PASS_PERCENT = 100
MAX_QUESTIONS = 20


class StandardError(Exception):
    """Нарушение правил базы стандартов (уходит в API как 400)."""


@dataclass(frozen=True)
class CheckResult:
    """Итог попытки: сколько верно, какой процент, сдал ли."""

    total: int
    correct: int
    percent: int
    passed: bool


# --------------------------------------------------------------------------
# Чистые правила
# --------------------------------------------------------------------------


def grade(
    correct_indexes: list[int], answers: list[int], pass_percent: int
) -> CheckResult:
    """Сверить ответы с ключом. Пустой тест сдать нельзя.

    Ответы вне диапазона вариантов считаются неверными — приходит массив
    индексов, и «придумать» себе вариант клиент не может.
    """
    total = len(correct_indexes)
    if total == 0:
        raise StandardError("no_questions")

    correct = sum(
        1
        for expected, given in zip(correct_indexes, answers, strict=False)
        if given == expected
    )
    percent = round(correct * 100 / total)
    threshold = min(max(pass_percent, MIN_PASS_PERCENT), MAX_PASS_PERCENT)
    return CheckResult(
        total=total, correct=correct, percent=percent, passed=percent >= threshold
    )


def visible_filter(employee: Employee):
    """Стандарт виден, если он общий или из подразделения сотрудника."""
    if employee.department_id is None:
        return Standard.department_id.is_(None)
    return or_(
        Standard.department_id.is_(None),
        Standard.department_id == employee.department_id,
    )


# --------------------------------------------------------------------------
# Выборки
# --------------------------------------------------------------------------


async def list_standards(
    session: AsyncSession, employee: Employee, *, active_only: bool = True
) -> list[Standard]:
    stmt = select(Standard).where(visible_filter(employee))
    if active_only:
        stmt = stmt.where(Standard.is_active.is_(True))
    stmt = stmt.order_by(Standard.sort_order, Standard.id)
    return list((await session.scalars(stmt)).all())


async def get_standard(session: AsyncSession, standard_id: int) -> Standard | None:
    return await session.get(Standard, standard_id)


def can_view(employee: Employee, standard: Standard) -> bool:
    """Общий стандарт или стандарт своего подразделения."""
    return standard.department_id in (None, employee.department_id)


async def questions_of(
    session: AsyncSession, standard_id: int
) -> list[StandardQuestion]:
    rows = await session.scalars(
        select(StandardQuestion)
        .where(StandardQuestion.standard_id == standard_id)
        .order_by(StandardQuestion.sort_order, StandardQuestion.id)
    )
    return list(rows.all())


async def last_attempt(
    session: AsyncSession, standard_id: int, employee_id: int
) -> StandardCheck | None:
    return await session.scalar(
        select(StandardCheck)
        .where(
            StandardCheck.standard_id == standard_id,
            StandardCheck.employee_id == employee_id,
        )
        .order_by(StandardCheck.at.desc(), StandardCheck.id.desc())
    )


async def passed_ids(session: AsyncSession, employee_id: int) -> set[int]:
    """Стандарты, которые человек уже сдал (любой успешной попыткой)."""
    rows = await session.scalars(
        select(StandardCheck.standard_id).where(
            StandardCheck.employee_id == employee_id,
            StandardCheck.passed.is_(True),
        )
    )
    return {int(value) for value in rows.all()}


async def progress(
    session: AsyncSession, employee: Employee
) -> tuple[int, int]:
    """(сдано, всего) — для строки прогресса в профиле."""
    standards = await list_standards(session, employee)
    if not standards:
        return 0, 0
    done = await passed_ids(session, employee.id)
    return len([s for s in standards if s.id in done]), len(standards)


# --------------------------------------------------------------------------
# Прохождение теста
# --------------------------------------------------------------------------


async def submit_check(
    session: AsyncSession,
    standard: Standard,
    *,
    employee: Employee,
    answers: list[int],
) -> StandardCheck:
    """Проверить ответы и записать попытку. Коммитит вызывающий."""
    if standard.department_id not in (None, employee.department_id):
        raise StandardError("standard_not_available")
    if not standard.is_active:
        raise StandardError("standard_inactive")

    questions = await questions_of(session, standard.id)
    if len(answers) != len(questions):
        raise StandardError("answers_count_mismatch")

    result = grade(
        [q.correct_index for q in questions], answers, standard.pass_percent
    )
    check = StandardCheck(
        standard_id=standard.id,
        employee_id=employee.id,
        total=result.total,
        correct=result.correct,
        percent=result.percent,
        passed=result.passed,
        answers=list(answers),
    )
    session.add(check)
    await session.flush()
    log.info(
        "hr.standard_checked",
        standard_id=standard.id,
        employee_id=employee.id,
        percent=result.percent,
        passed=result.passed,
    )
    return check


# --------------------------------------------------------------------------
# Наполнение (руководитель/админ)
# --------------------------------------------------------------------------


async def create_standard(
    session: AsyncSession,
    *,
    title: str,
    body: str,
    category: str = "other",
    emoji: str | None = None,
    summary: str | None = None,
    department_id: int | None = None,
    pass_percent: int = DEFAULT_PASS_PERCENT,
    is_required: bool = False,
    sort_order: int = 0,
    questions: list[tuple[str, list[str], int]] | None = None,
) -> Standard:
    clean_title = (title or "").strip()
    clean_body = (body or "").strip()
    if not clean_title:
        raise StandardError("empty_title")
    if not clean_body:
        raise StandardError("empty_body")
    if category not in STANDARD_CATEGORIES:
        raise StandardError("bad_category")
    if department_id is not None:
        from app.services import hr_departments

        dept = await hr_departments.get_department(session, department_id)
        if dept is None:
            raise StandardError("department_unavailable")

    standard = Standard(
        title=clean_title[:200],
        body=clean_body,
        category=category,
        emoji=(emoji or "").strip()[:16] or None,
        summary=(summary or "").strip() or None,
        department_id=department_id,
        pass_percent=min(max(pass_percent, MIN_PASS_PERCENT), MAX_PASS_PERCENT),
        is_required=is_required,
        sort_order=sort_order,
        is_active=True,
    )
    session.add(standard)
    await session.flush()
    await replace_questions(session, standard.id, questions or [])
    return standard


async def update_standard(
    session: AsyncSession,
    standard: Standard,
    *,
    is_required: bool | None = None,
    is_active: bool | None = None,
    pass_percent: int | None = None,
) -> Standard:
    """Точечная правка признаков без переписывания текста и вопросов.

    Обязательность и порог меняются чаще всего — отдельная ручка избавляет от
    повторной отправки всей инструкции и теста (и от риска потерять вопросы при
    частичном апдейте). Коммитит вызывающий.
    """
    if is_required is not None:
        standard.is_required = is_required
    if is_active is not None:
        standard.is_active = is_active
    if pass_percent is not None:
        standard.pass_percent = min(
            max(pass_percent, MIN_PASS_PERCENT), MAX_PASS_PERCENT
        )
    await session.flush()
    return standard


async def replace_questions(
    session: AsyncSession,
    standard_id: int,
    questions: list[tuple[str, list[str], int]],
) -> None:
    """Полная замена вопросов: правка теста — редкое и цельное действие."""
    if len(questions) > MAX_QUESTIONS:
        raise StandardError("too_many_questions")

    existing = await questions_of(session, standard_id)
    for row in existing:
        await session.delete(row)
    await session.flush()

    for index, (text, options, correct_index) in enumerate(questions):
        clean_text = (text or "").strip()
        clean_options = [str(option).strip() for option in options if str(option).strip()]
        if not clean_text:
            raise StandardError("empty_question")
        if len(clean_options) < 2:
            raise StandardError("too_few_options")
        if not 0 <= correct_index < len(clean_options):
            raise StandardError("bad_correct_index")
        session.add(
            StandardQuestion(
                standard_id=standard_id,
                text=clean_text[:500],
                options=clean_options,
                correct_index=correct_index,
                sort_order=index,
            )
        )
    await session.flush()


async def summary_stats(session: AsyncSession, employee: Employee) -> dict[str, int]:
    """Сколько стандартов сдано и сколько попыток было — для профиля."""
    total_standards = len(await list_standards(session, employee))
    attempts = int(
        await session.scalar(
            select(func.count())
            .select_from(StandardCheck)
            .where(StandardCheck.employee_id == employee.id)
        )
        or 0
    )
    done = len(await passed_ids(session, employee.id))
    return {"standards": total_standards, "passed": done, "attempts": attempts}
