"""Сброс текущей работы: «снести всё, что висит» с двойным подтверждением.

Зачем это вообще нужно. После тестового прогона в приложении остаются десятки
поручений, просрочек и проблем, которые никто и никогда не закроет: они шумят в
кабинете, в отчёте и в эскалации. Ручное удаление по одному — это полчаса
тапов, поэтому есть одна кнопка.

Что удаляется: **незакрытые** поручения (всё, кроме `done`) и **открытые**
проблемы журнала. Завершённые задачи, KPI, опыт и история сдач остаются — это
не «сброс базы», а уборка текучки.

Безопасность в трёх слоях:

1. **Права.** Администратор убирает всё, руководитель — только своё
   подразделение. АУП без отдела — только задачи, где он исполнитель или автор:
   «управляющий вообще» не должен одной кнопкой обнулить чужую работу.
2. **Двойное подтверждение.** Сначала `preview` — сухой счёт и одноразовый
   токен. Затем `execute` с этим токеном и словом-подтверждением. Токен
   подписан и живёт 10 минут; если данные изменились, токен перестаёт
   совпадать — значит, показывали не то, что удаляем.
3. **Границы.** Демо-пул `[BOT]` сюда не попадает: им управляет отдельная
   ручка (`hr_demo.purge`), и смешивать «убрать боевые хвосты» с «снести
   симуляторов» нельзя.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field

import structlog
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.hr_models import (
    TASK_DONE,
    Employee,
    Issue,
    Task,
    TaskAssignment,
    TaskEvent,
    TaskPhoto,
)
from app.db.models import AppNotification
from app.services import hr_access, hr_demo

log = structlog.get_logger()

CONFIRM_WORD = "СБРОС"
TOKEN_TTL_SECONDS = 10 * 60
# Открытые проблемы: те же статусы, что в журнале (`hr_issues`).
OPEN_ISSUE_STATUSES: tuple[str, ...] = ("open", "in_progress")

# Уведомления по поручениям: `task_*` и `task_escalated`. Payload у них всегда
# содержит `task_id`, поэтому после удаления задач такие строки — битые ссылки.
_TASK_NOTIFICATION_PREFIX = "task_"


@dataclass(frozen=True)
class ResetScope:
    """Кто и что может убрать."""

    employee_id: int
    is_admin: bool
    department_id: int | None
    description: str

    @property
    def key(self) -> str:
        return f"{self.employee_id}:{int(self.is_admin)}:{self.department_id or 0}"


@dataclass(frozen=True)
class ResetCounts:
    tasks: int = 0
    assignments: int = 0
    events: int = 0
    photos: int = 0
    issues: int = 0
    notifications: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "tasks": self.tasks,
            "assignments": self.assignments,
            "events": self.events,
            "photos": self.photos,
            "issues": self.issues,
            "notifications": self.notifications,
        }


@dataclass(frozen=True)
class ResetPreview:
    scope: ResetScope
    counts: ResetCounts
    token: str
    expires_in_seconds: int = TOKEN_TTL_SECONDS
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Чистые правила
# --------------------------------------------------------------------------


def resolve_scope(employee: Employee) -> ResetScope:
    """Область сброса по роли. Руководитель не может выйти за свой отдел."""
    if hr_access.role_rank(employee.role) >= hr_access.role_rank("admin"):
        return ResetScope(
            employee_id=int(employee.id),
            is_admin=True,
            department_id=None,
            description="всё, что не закрыто",
        )
    if employee.department_id is not None:
        return ResetScope(
            employee_id=int(employee.id),
            is_admin=False,
            department_id=int(employee.department_id),
            description="незакрытое в своём подразделении",
        )
    return ResetScope(
        employee_id=int(employee.id),
        is_admin=False,
        department_id=None,
        description="только свои поручения (отдел не назначен)",
    )


def _sign(payload: str) -> str:
    key = get_settings().bot_token.encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def make_token(scope: ResetScope, counts: ResetCounts, *, now: int | None = None) -> str:
    """Токен привязан к счёту и к тому, кто его получил.

    Счёт в подписи — это защита от «показали 3 задачи, удалили 30»: если между
    предпросмотром и подтверждением данные изменились, токен не сойдётся.
    """
    expires = (now or int(time.time())) + TOKEN_TTL_SECONDS
    payload = f"{scope.key}:{counts.tasks}:{counts.issues}:{expires}"
    return f"{expires}.{_sign(payload)}"


def verify_token(
    token: str, scope: ResetScope, counts: ResetCounts, *, now: int | None = None
) -> bool:
    """Проверить подпись и срок. Ошибка = «обнови предпросмотр»."""
    if not token or "." not in token:
        return False
    raw_expires, signature = token.split(".", 1)
    try:
        expires = int(raw_expires)
    except ValueError:
        return False
    moment = now or int(time.time())
    if expires < moment:
        return False
    payload = f"{scope.key}:{counts.tasks}:{counts.issues}:{expires}"
    return hmac.compare_digest(signature, _sign(payload))


# --------------------------------------------------------------------------
# Выборки
# --------------------------------------------------------------------------


async def _demo_ids(session: AsyncSession) -> set[int]:
    return await hr_demo.demo_employee_ids(session)


def _task_filter(scope: ResetScope, demo_ids: set[int]):
    """Незакрытые задачи в области прав, без тестового пула."""
    conditions = [Task.status != TASK_DONE]
    if scope.is_admin:
        pass
    elif scope.department_id is not None:
        department_people = select(Employee.id).where(
            Employee.department_id == scope.department_id
        )
        conditions.append(
            or_(
                Task.department_id == scope.department_id,
                Task.assignee_employee_id.in_(department_people),
            )
        )
    else:
        conditions.append(
            or_(
                Task.assignee_employee_id == scope.employee_id,
                Task.created_by_employee_id == scope.employee_id,
            )
        )
    if demo_ids:
        conditions.append(
            or_(
                Task.assignee_employee_id.is_(None),
                Task.assignee_employee_id.notin_(demo_ids),
            )
        )
    return conditions


def _issue_filter(scope: ResetScope, demo_ids: set[int]):
    conditions = [Issue.status.in_(OPEN_ISSUE_STATUSES)]
    if not scope.is_admin:
        if scope.department_id is not None:
            conditions.append(Issue.department_id == scope.department_id)
        else:
            conditions.append(
                or_(
                    Issue.employee_id == scope.employee_id,
                    Issue.assignee_employee_id == scope.employee_id,
                )
            )
    if demo_ids:
        conditions.append(
            or_(Issue.employee_id.is_(None), Issue.employee_id.notin_(demo_ids))
        )
    return conditions


async def _collect(
    session: AsyncSession, scope: ResetScope
) -> tuple[list[int], list[int], ResetCounts]:
    demo_ids = await _demo_ids(session)
    task_ids = [
        int(value)
        for value in (
            await session.scalars(select(Task.id).where(*_task_filter(scope, demo_ids)))
        ).all()
    ]
    issue_ids = [
        int(value)
        for value in (
            await session.scalars(select(Issue.id).where(*_issue_filter(scope, demo_ids)))
        ).all()
    ]

    counts = ResetCounts(tasks=len(task_ids), issues=len(issue_ids))
    if task_ids:
        counts = ResetCounts(
            tasks=len(task_ids),
            issues=len(issue_ids),
            assignments=int(
                await session.scalar(
                    select(func.count())
                    .select_from(TaskAssignment)
                    .where(TaskAssignment.task_id.in_(task_ids))
                )
                or 0
            ),
            events=int(
                await session.scalar(
                    select(func.count())
                    .select_from(TaskEvent)
                    .where(TaskEvent.task_id.in_(task_ids))
                )
                or 0
            ),
            photos=int(
                await session.scalar(
                    select(func.count())
                    .select_from(TaskPhoto)
                    .where(TaskPhoto.task_id.in_(task_ids))
                )
                or 0
            ),
            notifications=int(
                await session.scalar(
                    select(func.count())
                    .select_from(AppNotification)
                    .where(
                        AppNotification.kind.like(f"{_TASK_NOTIFICATION_PREFIX}%"),
                        AppNotification.payload["task_id"].astext.in_(
                            [str(value) for value in task_ids]
                        ),
                    )
                )
                or 0
            ),
        )
    return task_ids, issue_ids, counts


# --------------------------------------------------------------------------
# API сервиса
# --------------------------------------------------------------------------


async def preview(session: AsyncSession, employee: Employee) -> ResetPreview:
    """Сколько всего исчезнет — и токен на подтверждение. Ничего не удаляет."""
    scope = resolve_scope(employee)
    _task_ids, _issue_ids, counts = await _collect(session, scope)
    notes = [
        "Завершённые поручения, KPI и история сдач остаются.",
        "Тестовый пул [BOT] сбрасывается отдельной кнопкой в профиле админа.",
    ]
    if scope.department_id is None and not scope.is_admin:
        notes.append("Отдел не назначен — убираем только твои поручения.")
    return ResetPreview(
        scope=scope, counts=counts, token=make_token(scope, counts), notes=notes
    )


async def execute(
    session: AsyncSession,
    employee: Employee,
    *,
    token: str,
    confirm: str,
) -> ResetCounts:
    """Удалить показанное. Требует токен предпросмотра и слово `СБРОС`."""
    if (confirm or "").strip().upper() != CONFIRM_WORD:
        raise hr_access.HrAccessError("confirm_word_required")
    scope = resolve_scope(employee)
    task_ids, issue_ids, counts = await _collect(session, scope)
    if not verify_token(token, scope, counts):
        raise hr_access.HrAccessError("reset_preview_stale")

    if issue_ids:
        # События карточки уходят каскадом (`hr_issue_events.issue_id`).
        await session.execute(delete(Issue).where(Issue.id.in_(issue_ids)))
    if task_ids:
        # Дети `tasks` (отметки/события/фото/объяснения) — FK CASCADE.
        await session.execute(
            delete(AppNotification).where(
                AppNotification.kind.like(f"{_TASK_NOTIFICATION_PREFIX}%"),
                AppNotification.payload["task_id"].astext.in_(
                    [str(value) for value in task_ids]
                ),
            )
        )
        await session.execute(delete(Task).where(Task.id.in_(task_ids)))
    await session.commit()

    log.info(
        "hr.reset_done",
        employee_id=int(employee.id),
        admin=scope.is_admin,
        tasks=counts.tasks,
        issues=counts.issues,
    )
    return counts


def preview_text(preview_obj: ResetPreview) -> str:
    """Текст подтверждения для бота и приложения (одна формулировка)."""
    counts = preview_obj.counts
    lines = [
        "🧹 <b>Сброс текущей работы</b>",
        "",
        f"Область: {preview_obj.scope.description}.",
        f"Поручений: <b>{counts.tasks}</b> (отметок {counts.assignments}, "
        f"событий {counts.events}, фото {counts.photos})",
        f"Проблем журнала: <b>{counts.issues}</b>",
        f"Уведомлений по ним: {counts.notifications}",
    ]
    if counts.tasks == 0 and counts.issues == 0:
        lines.append("")
        lines.append("Сбрасывать нечего — всё уже закрыто.")
    lines.append("")
    lines.append("Завершённые поручения и история остаются.")
    lines.append("Действие необратимо.")
    return "\n".join(lines)


__all__ = [
    "CONFIRM_WORD",
    "ResetCounts",
    "ResetPreview",
    "ResetScope",
    "execute",
    "make_token",
    "preview",
    "preview_text",
    "resolve_scope",
    "verify_token",
]
