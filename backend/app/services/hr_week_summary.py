"""Недельная сводка «что мешало смене».

Зачем отдельно от дневного отчёта. Дневной отвечает «как прошла смена»:
сколько людей, что сделано, что висит. Но руководитель, разбирающий проблемы,
задаёт другой вопрос — «что нас тормозит неделю за неделей». На него нельзя
ответить одним днём: одна сломанная посудомойка в четверг — случайность, та же
поломка три раза за неделю — причина, с которой надо что-то делать.

Поэтому здесь не срез, а три вещи подряд:

1. **счётчики недели** — новые и закрытые проблемы, сделанные и просроченные
   поручения;
2. **категории** — что именно мешало чаще всего: оборудование, гости, склад;
3. **список** — конкретные проблемы за период с возрастом, чтобы было видно,
   что стоит неделю, а что закрыли за час.

Почему считаем по локальному поясу организации. «Неделя» начинается в полночь
по времени зала, а не UTC: иначе понедельничная смена попала бы в воскресенье,
и сводка разошлась бы с графиком.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import TASK_DONE, TASK_OVERDUE, Issue, Task
from app.services import hr_issues, hr_reports, hr_settings

# Семь дней — потому что смена повторяется неделей; месяц уже не читается с
# телефона, а день не показывает повторов.
DAYS = 7
BLOCKER_LIMIT = 10
CATEGORY_LIMIT = 5


@dataclass(frozen=True)
class CategoryRow:
    category: str
    count: int


@dataclass(frozen=True)
class Blocker:
    issue_id: int
    title: str
    category: str
    status: str
    created_at: datetime
    resolved_at: datetime | None
    age_hours: int


@dataclass(frozen=True)
class WeekSummary:
    start: date
    end: date
    issues_new: int
    issues_closed: int
    issues_open: int
    tasks_done: int
    tasks_done_late: int
    tasks_overdue_open: int
    categories: list[CategoryRow] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)


def period(now: datetime) -> tuple[date, date]:
    """Последние семь дней, включая сегодняшний."""
    end = now.date()
    return end - timedelta(days=DAYS - 1), end


def age_hours(created_at: datetime, now: datetime) -> int:
    """Сколько часов проблема живёт. Отрицательное не бывает: часы базы и
    приложения расходятся, и «-1 ч» в списке читается как ошибка."""
    moment = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    return max(0, int((now - moment).total_seconds() // 3600))


async def build(
    session: AsyncSession,
    *,
    viewer,  # noqa: ANN001 — Employee
    department_id: int | None = None,
    now: datetime | None = None,
) -> WeekSummary:
    moment = hr_settings.local_now(now)
    start, end = period(moment)
    tz = moment.tzinfo
    since = datetime.combine(start, time.min, tzinfo=tz)

    _scope, department = hr_reports.resolve_scope(viewer, department_id)
    issue_filters = [Issue.created_at >= since]
    task_filters = []
    if department is not None:
        issue_filters.append(Issue.department_id == department)
        task_filters.append(Task.department_id == department)

    issues_new = int(
        await session.scalar(
            select(func.count()).select_from(Issue).where(*issue_filters)
        )
        or 0
    )
    issues_closed = int(
        await session.scalar(
            select(func.count())
            .select_from(Issue)
            .where(
                Issue.resolved_at.is_not(None),
                Issue.resolved_at >= since,
                *([Issue.department_id == department] if department else []),
            )
        )
        or 0
    )
    issues_open = int(
        await session.scalar(
            select(func.count())
            .select_from(Issue)
            .where(
                Issue.status.in_(tuple(hr_issues.OPEN_STATUSES)),
                *([Issue.department_id == department] if department else []),
            )
        )
        or 0
    )

    category_rows = (
        await session.execute(
            select(Issue.category, func.count())
            .where(*issue_filters)
            .group_by(Issue.category)
            .order_by(func.count().desc(), Issue.category)
            .limit(CATEGORY_LIMIT)
        )
    ).all()
    categories = [CategoryRow(str(name), int(count)) for name, count in category_rows]

    done_filters = [Task.status == TASK_DONE, Task.done_at.is_not(None), Task.done_at >= since, *task_filters]
    tasks_done = int(
        await session.scalar(select(func.count()).select_from(Task).where(*done_filters)) or 0
    )
    tasks_done_late = int(
        await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(*done_filters, Task.due_at.is_not(None), Task.done_at > Task.due_at)
        )
        or 0
    )
    tasks_overdue_open = int(
        await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.status == TASK_OVERDUE, *task_filters)
        )
        or 0
    )

    rows = (
        await session.scalars(
            select(Issue)
            .where(*issue_filters)
            .order_by(Issue.created_at.desc())
            .limit(BLOCKER_LIMIT)
        )
    ).all()
    blockers = [
        Blocker(
            issue_id=int(issue.id),
            title=issue.title,
            category=issue.category,
            status=issue.status,
            created_at=issue.created_at,
            resolved_at=issue.resolved_at,
            age_hours=age_hours(issue.created_at, moment),
        )
        for issue in rows
    ]

    return WeekSummary(
        start=start,
        end=end,
        issues_new=issues_new,
        issues_closed=issues_closed,
        issues_open=issues_open,
        tasks_done=tasks_done,
        tasks_done_late=tasks_done_late,
        tasks_overdue_open=tasks_overdue_open,
        categories=categories,
        blockers=blockers,
    )


__all__ = [
    "Blocker",
    "CategoryRow",
    "WeekSummary",
    "age_hours",
    "build",
    "period",
]
