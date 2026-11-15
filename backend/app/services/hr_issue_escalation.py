"""Эскалация проблем по времени: сначала напомнить, потом позвать руководителя.

Зачем это вообще. Проблема в журнале живёт дольше, чем смена: её завели,
назначили официанту, а он ушёл на выходные. Через два дня карточка всё ещё
«открыта», и никто не виноват — просто никто не заметил. Сроки у проблем не
ставятся (в отличие от поручений), поэтому единственный сигнал — тишина.

Две ступени, как у просрочки поручения:

1. **через 4 часа без движения** — напоминание назначенному: «висит, посмотри»;
2. **через 12 часов после этого** — руководителям отдела и админам: «назначенный
   не ответил, нужен ты».

«Без движения» — это время с последнего события карточки: создания, смены
статуса, назначения или комментария. Считаем по истории (`IssueEvent`), а не по
`updated_at`: комментарий не обязан трогать саму строку проблемы, а активностью
является именно он.

Идемпотентность — маркером в той же истории (`stale_reminder_sent`,
`escalated_to_manager`), как у задач. Повторный тик видит маркер и молчит;
новая активность после напоминания не сбрасывает счёт — иначе человек, который
ответил «разбираюсь», навсегда откладывает проблему.

Канал: уведомление в приложении + событийный push (с потолком и выключателем
`events`). В Telegram-личку не пишем: у проблем нет своего вида подписки, а
городить второй канал без выключателя — прямая дорога к тому, что человек
отключит уведомления совсем.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    ROLE_ADMIN,
    ROLE_AUP,
    Employee,
    Issue,
    IssueEvent,
)
from app.services import hr_issues, hr_notify

log = structlog.get_logger()

# Пороги держим в коде, а не в настройках: это не бизнес-правило «сколько ждать
# гостя», а гигиена журнала. Настройка появляется, когда владелец захочет
# менять её сам; до тех пор лишний ключ в админке только путает.
REMINDER_AFTER = timedelta(hours=4)
ESCALATE_AFTER = timedelta(hours=12)

EVENT_REMINDER = "stale_reminder_sent"
EVENT_ESCALATED = "escalated_to_manager"
MARKER_KINDS: tuple[str, ...] = (EVENT_REMINDER, EVENT_ESCALATED)

# За один тик больше не берём: после долгого простоя не должно быть лавины.
BATCH = 100


@dataclass(frozen=True)
class Plan:
    """Что сделать с проблемой на этом тике."""

    issue: Issue
    step: str  # "reminder" | "manager"
    recipients: tuple[Employee, ...]
    idle: timedelta


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _activity(session: AsyncSession, issues: list[Issue]) -> dict[int, datetime]:
    """Последняя активность по каждой карточке: время её последнего события.

    Один запрос на пачку, а не по одному на проблему: тик ходит каждые 15
    минут, и N+1 здесь — это N запросов в базу каждые четверть часа.
    """
    ids = [int(issue.id) for issue in issues]
    if not ids:
        return {}
    rows = await session.execute(
        select(IssueEvent.issue_id, func.max(IssueEvent.at))
        .where(IssueEvent.issue_id.in_(ids))
        .group_by(IssueEvent.issue_id)
    )
    latest = {int(issue_id): _aware(at) for issue_id, at in rows.all()}
    result: dict[int, datetime] = {}
    for issue in issues:
        candidates = [
            moment
            for moment in (
                _aware(issue.created_at),
                _aware(issue.updated_at),
                latest.get(int(issue.id)),
            )
            if moment is not None
        ]
        if candidates:
            result[int(issue.id)] = max(candidates)
    return result


async def _markers(session: AsyncSession, ids: list[int]) -> dict[int, str]:
    """Последний маркер эскалации по каждой проблеме (вид, не время)."""
    if not ids:
        return {}
    rows = await session.execute(
        select(IssueEvent.issue_id, IssueEvent.kind, IssueEvent.at)
        .where(
            IssueEvent.issue_id.in_(ids),
            IssueEvent.kind.in_(MARKER_KINDS),
        )
        .order_by(IssueEvent.at)
    )
    last: dict[int, str] = {}
    for issue_id, kind, _at in rows.all():
        last[int(issue_id)] = str(kind)
    return last


async def _managers_of(session: AsyncSession, issue: Issue) -> list[Employee]:
    """Руководители отдела проблемы и админы. Админ видит всё, поэтому он тут.

    Отдел проблемы, а не отдела назначенного: эскалация идёт по месту, где
    проблема случилась, даже если ответственный из другого отдела.
    """
    conditions = [Employee.role == ROLE_ADMIN]
    if issue.department_id is not None:
        conditions.append(
            (Employee.role == ROLE_AUP)
            & (Employee.department_id == issue.department_id)
        )
    rows = await session.scalars(
        select(Employee).where(Employee.is_active.is_(True), or_(*conditions))
    )
    return list(rows.all())


async def plan(
    session: AsyncSession, *, now: datetime | None = None
) -> list[Plan]:
    """Кому и что отправить прямо сейчас. Чистая функция от базы — для тестов."""
    moment = now or datetime.now(UTC)
    issues = list(
        (
            await session.scalars(
                select(Issue)
                .where(Issue.status.in_(tuple(hr_issues.OPEN_STATUSES)))
                .order_by(Issue.created_at)
                .limit(BATCH)
            )
        ).all()
    )
    if not issues:
        return []

    ids = [int(issue.id) for issue in issues]
    activity = await _activity(session, issues)
    markers = await _markers(session, ids)

    planned: list[Plan] = []
    for issue in issues:
        since = activity.get(int(issue.id))
        if since is None:
            continue
        idle = moment - since
        last = markers.get(int(issue.id))

        if last == EVENT_ESCALATED:
            # Вторая ступень пройдена: дальше молчим до закрытия или новой
            # карточки. Иначе руководитель получает одно и то же каждые 15 минут.
            continue

        if last == EVENT_REMINDER:
            if idle < ESCALATE_AFTER:
                continue
            recipients = tuple(await _managers_of(session, issue))
            if recipients:
                planned.append(Plan(issue, "manager", recipients, idle))
            continue

        if idle < REMINDER_AFTER:
            continue
        if issue.assignee_employee_id is not None:
            assignee = await session.get(Employee, issue.assignee_employee_id)
            recipients = (
                (assignee,)
                if assignee is not None and assignee.is_active
                else tuple(await _managers_of(session, issue))
            )
        else:
            # Назначенного нет — ждать некого, сразу зовём руководителя.
            recipients = tuple(await _managers_of(session, issue))
        if recipients:
            planned.append(Plan(issue, "reminder", recipients, idle))
    return planned


async def run(
    session: AsyncSession, *, now: datetime | None = None
) -> int:
    """Отправить всё, что созрело, и поставить маркеры. Возвращает число проблем."""
    from app.services import hr_simulation

    if hr_simulation.current() is not None:
        return 0

    planned = await plan(session, now=now)
    sent = 0
    for item in planned:
        hours = max(1, int(item.idle.total_seconds() // 3600))
        text = (
            hr_notify.issue_stale_text(item.issue, hours)
            if item.step == "reminder"
            else hr_notify.issue_escalated_text(item.issue, hours)
        )
        kind = (
            hr_notify.KIND_ISSUE_STALE
            if item.step == "reminder"
            else hr_notify.KIND_ISSUE_ESCALATED
        )
        await hr_notify.notify(
            session,
            employees=list(item.recipients),
            kind=kind,
            text=text,
            payload={"issue_id": item.issue.id},
        )
        await hr_notify.push_event(
            session,
            employees=list(item.recipients),
            title=(
                "Проблема без движения"
                if item.step == "reminder"
                else "Проблема ждёт руководителя"
            ),
            body=text,
            tag=f"issue_stale:{item.issue.id}",
        )
        session.add(
            IssueEvent(
                issue_id=item.issue.id,
                kind=EVENT_REMINDER if item.step == "reminder" else EVENT_ESCALATED,
                comment=f"{item.step} после {hours} ч без движения",
            )
        )
        sent += 1
    if planned:
        log.info("issue_escalation.sent", count=sent)
    return sent


__all__ = [
    "ESCALATE_AFTER",
    "EVENT_ESCALATED",
    "EVENT_REMINDER",
    "Plan",
    "REMINDER_AFTER",
    "plan",
    "run",
]
