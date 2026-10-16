"""Обратная связь по окончании смены (п.7 mainPROMT).

Вопросы настраивает администратор (`FeedbackQuestion`, `kind`:
`scale`/`choice`/`text`), сотрудник отвечает раз за смену (дату). Ответы
хранятся по одному на (сотрудник, дата, вопрос) — повторная отправка
перезаписывает значение, а не плодит строки.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    QUESTION_CHOICE,
    QUESTION_SCALE,
    QUESTION_TEXT,
    Employee,
    FeedbackAnswer,
    FeedbackQuestion,
)


class FeedbackError(Exception):
    pass


async def list_questions(
    session: AsyncSession, *, active_only: bool = True
) -> list[FeedbackQuestion]:
    stmt = select(FeedbackQuestion)
    if active_only:
        stmt = stmt.where(FeedbackQuestion.is_active.is_(True))
    stmt = stmt.order_by(FeedbackQuestion.sort_order, FeedbackQuestion.id)
    return list(await session.scalars(stmt))


async def get_question(
    session: AsyncSession, question_id: int
) -> FeedbackQuestion | None:
    return await session.get(FeedbackQuestion, question_id)


def validate_answer(
    question: FeedbackQuestion,
    *,
    value_scale: int | None,
    value_choice: str | None,
    value_text: str | None,
) -> None:
    """Проверить, что ответ соответствует виду вопроса."""
    if question.kind == QUESTION_SCALE:
        if value_scale is None or not (1 <= value_scale <= 5):
            raise FeedbackError("scale_out_of_range")
    elif question.kind == QUESTION_CHOICE:
        options = list(question.options or [])
        if not value_choice or value_choice not in options:
            raise FeedbackError("choice_not_in_options")
    elif question.kind == QUESTION_TEXT:
        if value_text is None or not value_text.strip():
            raise FeedbackError("empty_text")
    else:
        raise FeedbackError(f"unknown_kind:{question.kind}")


async def submit_answers(
    session: AsyncSession,
    *,
    employee: Employee,
    shift_date: date,
    answers: list[dict],
) -> list[FeedbackAnswer]:
    """Записать ответы за смену. `answers` — список словарей от API/бота.

    Неизвестный/неактивный вопрос — ошибка (не молчаливый пропуск): так кривой
    клиент не «съест» ответ, а получит понятную 400.
    """
    if not answers:
        raise FeedbackError("no_answers")

    stored: list[FeedbackAnswer] = []
    for raw in answers:
        question_id = raw.get("question_id")
        if not isinstance(question_id, int):
            raise FeedbackError("question_id_required")
        question = await get_question(session, question_id)
        if question is None or not question.is_active:
            raise FeedbackError(f"question_unavailable:{question_id}")

        value_scale = raw.get("value_scale")
        value_choice = raw.get("value_choice")
        value_text = raw.get("value_text")
        validate_answer(
            question,
            value_scale=value_scale,
            value_choice=value_choice,
            value_text=value_text,
        )

        existing = await session.scalar(
            select(FeedbackAnswer).where(
                FeedbackAnswer.employee_id == employee.id,
                FeedbackAnswer.shift_date == shift_date,
                FeedbackAnswer.question_id == question_id,
            )
        )
        if existing is None:
            existing = FeedbackAnswer(
                employee_id=employee.id,
                shift_date=shift_date,
                question_id=question_id,
            )
            session.add(existing)
        existing.value_scale = value_scale
        existing.value_choice = value_choice
        existing.value_text = value_text
        stored.append(existing)

    await session.flush()
    return stored


async def answers_for(
    session: AsyncSession,
    *,
    employee_id: int | None = None,
    shift_date: date | None = None,
) -> list[FeedbackAnswer]:
    """Выборка ответов: по сотруднику и/или дате (для отчётов АУП)."""
    stmt = select(FeedbackAnswer)
    if employee_id is not None:
        stmt = stmt.where(FeedbackAnswer.employee_id == employee_id)
    if shift_date is not None:
        stmt = stmt.where(FeedbackAnswer.shift_date == shift_date)
    stmt = stmt.order_by(FeedbackAnswer.shift_date.desc(), FeedbackAnswer.id)
    return list(await session.scalars(stmt))
