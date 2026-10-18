"""Обучение пользованию приложением — этап онбординга.

Раньше знакомство заканчивалось двумя вопросами (подразделение и опыт), и
человек оставался один на один с интерфейсом: где чек-лист, как отправить
фотоотчёт, кому уходит «не успеваю». Теперь после опыта идёт короткий курс из
семи экранов — по одному действию на урок, без стены текста.

Каталог живёт в коде: тексты описывают конкретный интерфейс и меняются вместе
с ним. В БД хранится только факт прохождения (`EmployeeTrainingStep`), поэтому
прогресс не сбрасывается и не дублируется.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import Employee, EmployeeTrainingStep


class TrainingError(Exception):
    """Неизвестный урок."""


@dataclass(frozen=True)
class Lesson:
    code: str
    title: str
    emoji: str
    minutes: int
    summary: str
    steps: tuple[str, ...]


# Порядок = порядок знакомства. Первые уроки про то, что человек делает
# каждый день, последние — про то, что нужно редко (настройки, уведомления).
LESSONS: tuple[Lesson, ...] = (
    Lesson(
        code="shift_start",
        title="Начать смену",
        emoji="🕒",
        minutes=1,
        summary="Чек-лист смены открывается первым — отметь пункты по порядку.",
        steps=(
            "Внизу нажми «Смена» — это твой чек-лист на сегодня.",
            "Пункты идут по порядку подготовки: рабочее место, оборудование, заготовки.",
            "Отметка сохраняется сразу: закрыл приложение — не потерял прогресс.",
        ),
    ),
    Lesson(
        code="photo_report",
        title="Фотоотчёт",
        emoji="📷",
        minutes=1,
        summary="Пункты с камерой нельзя закрыть без фото — так видно, что сделано.",
        steps=(
            "Напротив пункта с 📷 нажми «Фото».",
            "Сними рабочую зону так, чтобы было понятно, что проверял.",
            "Отправь — пункт закроется сам, отдельная галочка не нужна.",
        ),
    ),
    Lesson(
        code="my_tasks",
        title="Мои задачи",
        emoji="✅",
        minutes=1,
        summary="Поручения приходят на смену; срок и приоритет видны сразу.",
        steps=(
            "Вкладка «Задачи» — только то, что назначено тебе или твоему отделу.",
            "Задачу можно принять, начать и закрыть — статус виден руководителю.",
            "Просроченная задача остаётся в списке: её всё ещё можно выполнить.",
        ),
    ),
    Lesson(
        code="report_problem",
        title="Сообщить о проблеме",
        emoji="⚠️",
        minutes=1,
        summary="«Не успеваю» и поломки не теряются между сменами.",
        steps=(
            "Открой задачу и нажми «Есть проблема».",
            "Выбери причину и, если знаешь, когда сможешь сделать.",
            "Руководитель получит уведомление, а вопрос останется в журнале до решения.",
        ),
    ),
    Lesson(
        code="team_feed",
        title="События смены",
        emoji="📋",
        minutes=1,
        summary="Лента показывает, кто что сделал — без расспросов в чате.",
        steps=(
            "«События» — твои действия; руководитель видит свой отдел.",
            "Чек-листы, задачи и проблемы идут одной лентой по времени.",
            "Фильтры по человеку и отделу появляются у руководителя.",
        ),
    ),
    Lesson(
        code="links_standards",
        title="Ссылки и стандарты",
        emoji="🔗",
        minutes=1,
        summary="График, фудбук и регламенты — в одном разделе.",
        steps=(
            "«Ссылки» открывает то, что закреплено за твоим отделом.",
            "Если ссылки нет — попроси добавить руководителя, это настройка без разработчика.",
        ),
    ),
    Lesson(
        code="quiet_hours",
        title="Уведомления и тихие часы",
        emoji="🔔",
        minutes=1,
        summary="Алерты приходят в рабочее время ресторана, а не ночью.",
        steps=(
            "Руководитель задаёт часы работы один раз — на них равняются все смены.",
            "Вне окна уведомления копятся в приложении и не будят.",
            "Мьют на 24 часа / 3 дня / неделю / месяц — одна кнопка в настройках.",
        ),
    ),
)

LESSON_BY_CODE: dict[str, Lesson] = {lesson.code: lesson for lesson in LESSONS}
MANDATORY_CODES: tuple[str, ...] = tuple(lesson.code for lesson in LESSONS)


@dataclass(frozen=True)
class TrainingProgress:
    done: tuple[str, ...]
    total: int
    percent: int
    complete: bool

    def status(self) -> str:
        return "done" if self.complete else "in_progress"


def progress_from_codes(codes: set[str]) -> TrainingProgress:
    """Прогресс по уже пройденным кодам (чистая функция — для тестов)."""
    done = tuple(code for code in MANDATORY_CODES if code in codes)
    total = len(MANDATORY_CODES)
    percent = round(100 * len(done) / total) if total else 100
    return TrainingProgress(
        done=done, total=total, percent=percent, complete=len(done) == total
    )


async def completed_codes(session: AsyncSession, employee_id: int) -> set[str]:
    rows = await session.scalars(
        select(EmployeeTrainingStep.code).where(
            EmployeeTrainingStep.employee_id == employee_id
        )
    )
    return {str(code) for code in rows.all()}


async def progress(session: AsyncSession, employee: Employee) -> TrainingProgress:
    return progress_from_codes(await completed_codes(session, employee.id))


async def complete(
    session: AsyncSession, employee: Employee, code: str
) -> TrainingProgress:
    """Отметить урок пройденным. Идемпотентно: повтор не ломает и не дублирует.

    Коммитит вызывающий: урок и смена состояния онбординга — одна транзакция.
    """
    if code not in LESSON_BY_CODE:
        raise TrainingError(f"unknown_lesson:{code}")
    session.add(EmployeeTrainingStep(employee_id=employee.id, code=code))
    try:
        await session.flush()
    except IntegrityError:
        # Уже пройден — это не ошибка: кнопку могли нажать дважды.
        await session.rollback()
    return await progress(session, employee)
