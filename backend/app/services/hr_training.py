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

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import ONBOARDING_TRAINING, Employee, EmployeeTrainingStep


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
    # Уровень погружения (1..3). Уроки не «галочки», а шаги программы
    # адаптации: сначала базовое действие, потом рабочие задачи, потом
    # самостоятельная работа. Уровень показывается в курсе и влияет только
    # на порядок подачи — обязательность уроков от него не зависит.
    level: int = 1


# Порядок = порядок знакомства. Первые уроки про то, что человек делает
# каждый день, последние — про то, что нужно редко (настройки, уведомления).
LESSONS: tuple[Lesson, ...] = (
    Lesson(
        code="shift_start",
        level=1,
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
        level=1,
        title="Фотоотчёт",
        emoji="📷",
        minutes=1,
        summary="Пункты с камерой нельзя закрыть без фото — так видно, что сделано.",
        steps=(
            "Напротив пункта с 📷 нажми «📷 Снять отчёт» — откроется камера.",
            "Сними рабочую зону так, чтобы было понятно, что проверял.",
            "Отправь — пункт закроется сам, отдельная галочка не нужна.",
        ),
    ),
    Lesson(
        code="my_tasks",
        level=2,
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
        level=2,
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
        level=3,
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
        level=3,
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
        level=3,
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
class TrainingLevel:
    """Уровень программы: заголовок и что на нём осваивают."""

    level: int
    title: str
    hint: str


# Заголовки уровней правит администрация вместе с программой адаптации;
# в коде они лежат рядом с уроками, чтобы не расходиться с содержанием.
LEVELS: tuple[TrainingLevel, ...] = (
    TrainingLevel(
        level=1,
        title="Знакомство",
        hint="Базовые действия и главные правила.",
    ),
    TrainingLevel(
        level=2,
        title="Основные задачи",
        hint="Рабочие инструменты и первые проверки.",
    ),
    TrainingLevel(
        level=3,
        title="Самостоятельная работа",
        hint="Что делать в нестандартных ситуациях.",
    ),
)

LEVEL_BY_NUMBER: dict[int, TrainingLevel] = {item.level: item for item in LEVELS}


def level_of(code: str) -> int:
    lesson = LESSON_BY_CODE.get(code)
    return lesson.level if lesson else LEVELS[0].level


@dataclass(frozen=True)
class TrainingProgress:
    done: tuple[str, ...]
    total: int
    percent: int
    complete: bool

    def status(self) -> str:
        return "done" if self.complete else "in_progress"


def level_progress(codes: set[str]) -> tuple[tuple[TrainingLevel, int, int], ...]:
    """(уровень, пройдено, всего) — по каждому уровню, в порядке программы."""
    out: list[tuple[TrainingLevel, int, int]] = []
    for level in LEVELS:
        codes_here = [c for c in MANDATORY_CODES if level_of(c) == level.level]
        done = sum(1 for c in codes_here if c in codes)
        out.append((level, done, len(codes_here)))
    return tuple(out)


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


async def reset(session: AsyncSession, employee: Employee) -> TrainingProgress:
    """Начать курс заново: снять все уроки и вернуть онбординг в обучение.

    Нужно и разработчику (проверить сценарий «как у новичка»), и сотруднику,
    который хочет повторить материал. Отдел и опыт не трогаем: иначе человек
    провалился бы назад в вопросы первого запуска и получил бы другой чек-лист.
    """
    await session.execute(
        delete(EmployeeTrainingStep).where(
            EmployeeTrainingStep.employee_id == employee.id
        )
    )
    employee.onboarding_state = ONBOARDING_TRAINING
    employee.learning_mode = False
    await session.commit()
    return progress_from_codes(set())


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
