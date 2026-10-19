"""Джобы HR-ядра: напоминания о сроке и автоэскалация просрочки.

Один тик делает две вещи (бриф требует обе, правила настраиваются отдельно):

1. **Напоминание о приближающемся сроке.** Поручения, у которых `due_at`
   попадает в окно «сейчас … сейчас + N минут» и по которым напоминание ещё не
   отправлялось. Факт отправки фиксируем событием `TaskEvent` с комментарием
   `reminder_sent` — отдельной колонки не заводим, история и так пишется, а
   идемпотентность получается бесплатно (повторный тик не спамит).

2. **Эскалация просрочки.** Переводит открытые задачи с прошедшим сроком в
   `overdue` (`hr_tasks.sweep_overdue` — переход срабатывает ровно один раз,
   поэтому и уведомление уходит один раз) и уведомляет руководителей.

Куда уведомляем: **личные уведомления в мини-аппе** (основной канал, он уже
есть) + best-effort **личка в Telegram**, если сотрудник писал боту. В общий
групповой чат HR-события не уходят принципиально: поручения и просрочки — не
новость для всего зала.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.hr_models import (
    TASK_OVERDUE,
    Employee,
    Task,
    TaskEvent,
    TaskReminder,
)
from app.db.models import User
from app.services import hr_alerts, hr_demo, hr_notify, hr_settings, hr_tasks

log = structlog.get_logger()

# Комментарий события-маркера «напоминание отправлено».
REMINDER_EVENT_COMMENT = "reminder_sent"
# Маркер «вторая ступень отправлена»: отдельная колонка не нужна, история
# задачи и так пишется. Повторный тик видит маркер и не спамит.
SECOND_EVENT_COMMENT = "second_escalation_sent"

# Сколько задач максимум берём за один тик — защита от лавины после простоя.
BATCH_LIMIT = 200


# --------------------------------------------------------------------------
# Чистые правила
# --------------------------------------------------------------------------


def reminder_due(
    task: Task, now: datetime, before_minutes: int
) -> bool:
    """Пора ли напомнить: срок ещё не прошёл и близко.

    Просроченные задачи сюда НЕ попадают: у них своя ветка (эскалация), иначе
    сотрудник получил бы «напоминание» уже после дедлайна.
    """
    if task.due_at is None or task.status not in hr_tasks.OPEN_STATUSES:
        return False
    moment = now if now.tzinfo else now.replace(tzinfo=UTC)
    due = task.due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    if due < moment:
        return False
    return due <= moment + timedelta(minutes=before_minutes)


def unique_employees(employees: list[Employee]) -> list[Employee]:
    """Убрать дубли по `id`, сохранив порядок (один человек — одно уведомление)."""
    seen: set[int] = set()
    out: list[Employee] = []
    for employee in employees:
        if employee.id in seen:
            continue
        seen.add(employee.id)
        out.append(employee)
    return out


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def planned_reminder_at(
    due_at: datetime | None, before_minutes: int, override: TaskReminder | None = None
) -> datetime | None:
    """Когда по правилам должно уйти напоминание (с учётом ручной правки).

    Админка может передвинуть напоминание (`remind_at`) или выключить его
    (`skip`). Здесь одна точка правды: её используют и лента «запланировано»,
    и сам планировщик — иначе экран обещал бы одно, а чат присылал другое.
    """
    if override is not None and override.skip:
        return None
    if override is not None and override.remind_at is not None:
        return _aware(override.remind_at)
    if due_at is None:
        return None
    return _aware(due_at) - timedelta(minutes=max(0, int(before_minutes)))


def second_escalation_due(
    *,
    status: str,
    overdue_since: datetime | None,
    now: datetime,
    hours: int,
    already_sent: bool = False,
) -> bool:
    """Пора ли поднимать просрочку на вторую ступень (чистое правило).

    Условия: задача всё ещё `overdue` (любой другой статус — это реакция),
    известен момент просрочки, прошло не меньше `hours` и по задаче ещё не
    писали админам. `hours` зажимается снизу: нулевой порог превратил бы
    вторую ступень в дубль первой.
    """
    if already_sent or status != TASK_OVERDUE or overdue_since is None:
        return False
    elapsed = _aware(now) - _aware(overdue_since)
    return elapsed >= timedelta(hours=max(1, hours))


def marker_covers_cycle(
    marker_at: datetime | None,
    overdue_since: datetime | None,
    *,
    repeat_per_shift: bool = False,
    now: datetime | None = None,
) -> bool:
    """Закрывает ли старый маркер текущий цикл просрочки.

    Маркер — событие «админам уже писали». Если задача успела вернуться в
    работу и снова просрочилась, событие просрочки новее маркера — значит это
    другой цикл, и писать админам снова нужно.

    `repeat_per_shift` — строгий режим: пока задача висит, в каждой новой смене
    (то есть на следующий календарный день ресторана) админы получают
    напоминание заново. Маркер прошлой смены тогда цикл НЕ закрывает. Внутри
    одной смены повторной отправки нет — тик не спамит.
    """
    if marker_at is None:
        return False
    if repeat_per_shift:
        moment = _aware(now or datetime.now(UTC))
        tz = ZoneInfo(get_settings().scheduler_tz)
        if _aware(marker_at).astimezone(tz).date() != moment.astimezone(tz).date():
            return False
    if overdue_since is None:
        return True
    return _aware(marker_at) >= _aware(overdue_since)


async def admins(session: AsyncSession) -> list[Employee]:
    """Только администраторы бота — адресаты второй ступени.

    Руководителей здесь нет: они уже получили первый алерт, второй нужен
    именно тому, кто выше.
    """
    from app.db.hr_models import ROLE_ADMIN

    rows = await session.scalars(
        select(Employee).where(
            Employee.is_active.is_(True),
            Employee.role == ROLE_ADMIN,
        )
    )
    return list(rows.all())


def escalation_recipients(
    *, managers: list[Employee], creator: Employee | None
) -> list[Employee]:
    """Кому уходит эскалация просрочки: руководители + автор поручения.

    Дедуплицируем: автор обычно и есть руководитель, и получать два одинаковых
    уведомления ему незачем.
    """
    people = list(managers)
    if creator is not None:
        people.append(creator)
    return unique_employees(people)


# --------------------------------------------------------------------------
# Инфраструктура
# --------------------------------------------------------------------------


async def _reminded_task_ids(
    session: AsyncSession, task_ids: list[int]
) -> set[int]:
    """Задачи, по которым напоминание уже уходило (по событиям)."""
    if not task_ids:
        return set()
    rows = await session.scalars(
        select(TaskEvent.task_id).where(
            TaskEvent.task_id.in_(task_ids),
            TaskEvent.comment == REMINDER_EVENT_COMMENT,
        )
    )
    return {int(t) for t in rows.all()}


async def managers(session: AsyncSession) -> list[Employee]:
    """Все активные руководители и админы — адресаты эскалации и проблем."""
    from app.db.hr_models import ROLE_ADMIN, ROLE_AUP

    rows = await session.scalars(
        select(Employee).where(
            Employee.is_active.is_(True),
            Employee.role.in_((ROLE_AUP, ROLE_ADMIN)),
        )
    )
    return list(rows.all())


async def _telegram_ids(session: AsyncSession, employees: list[Employee]) -> dict[int, int]:
    """`employee.user_id` → `telegram_id` (один запрос на пачку)."""
    user_ids = [e.user_id for e in employees]
    if not user_ids:
        return {}
    rows = await session.execute(
        select(User.id, User.telegram_id).where(User.id.in_(user_ids))
    )
    return {int(uid): int(tg) for uid, tg in rows.all()}


async def send_dm(  # noqa: ANN001
    bot, telegram_id: int, text: str, keyboard=None
) -> bool:
    """Best-effort личка. Сотрудник мог не начинать диалог с ботом — это норма.

    Никаких исключений наружу: не доставленное личное сообщение не должно
    ломать тик планировщика. `keyboard` (опц.) — кнопки управления алертом
    прямо в сообщении (см. `hr_alerts.alert_keyboard`).
    """
    # Отрицательный ID — теневой профиль проверки: Telegram такое не принимает,
    # а реальному человеку сообщение не предназначено.
    if bot is None or not telegram_id or telegram_id <= 0 or not text:
        return False
    try:
        await bot.send_message(
            chat_id=telegram_id, text=text, parse_mode="HTML", reply_markup=keyboard
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.info("hr.dm_failed", telegram_id=telegram_id, error=str(exc))
        return False


async def _deliver(
    session: AsyncSession,
    *,
    bot,  # noqa: ANN001
    employees: list[Employee],
    kind: str,
    text: str,
    payload: dict | None = None,
    keyboard=None,  # noqa: ANN001
) -> None:
    """Личное уведомление в приложении + best-effort личка в Telegram.

    В чат пишем только в рабочее окно и вне ручного мьюта
    (`hr_settings.notifications_allowed`). Уведомление в приложении создаётся
    всегда: оно не звонит в 03:41 и не теряется, если человек откроет Mini App
    утром.
    """
    recipients = unique_employees(employees)
    if not recipients:
        return
    await hr_notify.notify(
        session, employees=recipients, kind=kind, text=text, payload=payload
    )
    if bot is None:
        return
    allowed, reason = await hr_settings.notifications_allowed(session)
    if not allowed:
        log.info("hr.dm_suppressed", reason=reason, kind=kind, recipients=len(recipients))
        return
    tg_map = await _telegram_ids(session, recipients)
    for employee in recipients:
        tg_id = tg_map.get(employee.user_id)
        if tg_id:
            await send_dm(bot, tg_id, text, keyboard)


# --------------------------------------------------------------------------
# Тик
# --------------------------------------------------------------------------


def _safe_bot():  # noqa: ANN202 — Bot | None
    """Бот для разовой отправки из API-ручки. Без него живём (только in-app)."""
    try:
        from app.bot.dispatcher import get_bot

        return get_bot()
    except Exception as exc:  # noqa: BLE001 — невалидный токен не должен ронять ручку
        log.info("hr.bot_unavailable", error=str(exc))
        return None


async def alert_managers(
    session: AsyncSession,
    *,
    employees: list[Employee],
    kind: str,
    text: str,
    task_id: int,
    bot=None,  # noqa: ANN001
) -> None:
    """Алерт руководителям с кнопками «решено / напомнить завтра / мьют».

    Одна точка входа для всех «тревожных» событий (просрочка, проблема), чтобы
    кнопки и тихие часы работали одинаково и не расползались по ручкам.
    """
    await _deliver(
        session,
        bot=bot if bot is not None else _safe_bot(),
        employees=employees,
        kind=kind,
        text=text,
        payload={"task_id": task_id},
        keyboard=hr_alerts.alert_keyboard(int(task_id)),
    )


def _simulation_employee_ids():
    """Подзапрос теневых профилей: их задачи не тревожат реальный контур."""
    return select(Employee.id).where(Employee.is_simulation.is_(True))


async def send_deadline_reminders(
    session: AsyncSession,
    *,
    bot=None,  # noqa: ANN001
    now: datetime | None = None,
    before_minutes: int | None = None,
) -> list[Task]:
    """Разослать напоминания по близким срокам. Возвращает затронутые задачи."""
    moment = now or datetime.now(UTC)
    window = (
        before_minutes
        if before_minutes is not None
        else await hr_settings.get_remind_before_minutes(session)
    )
    horizon = moment + timedelta(minutes=window)
    rows = await session.scalars(
        select(Task)
        .where(
            Task.due_at.is_not(None),
            Task.due_at > moment,
            # Обычное окно или ручной перенос, даже если он выходит за окно:
            # иначе «передвинуть на час» тихо не сработало бы.
            or_(
                Task.due_at <= horizon,
                Task.id.in_(
                    select(TaskReminder.task_id).where(
                        TaskReminder.remind_at.is_not(None),
                        TaskReminder.remind_at <= horizon,
                        TaskReminder.skip.is_(False),
                    )
                ),
            ),
            Task.status.in_(tuple(hr_tasks.OPEN_STATUSES)),
            # Задачи сеанса проверки живут только до выхода: напоминать о них
            # настоящим людям нельзя, а тень всё равно не прочитает DM.
            or_(
                Task.assignee_employee_id.is_(None),
                Task.assignee_employee_id.notin_(_simulation_employee_ids()),
            ),
        )
        .order_by(Task.due_at)
        .limit(BATCH_LIMIT)
    )
    candidates = list(rows.all())
    rules: dict[int, TaskReminder] = {}
    if candidates:
        for rule in (
            await session.scalars(
                select(TaskReminder).where(
                    TaskReminder.task_id.in_([int(task.id) for task in candidates])
                )
            )
        ).all():
            rules[int(rule.task_id)] = rule
    already = await _reminded_task_ids(session, [t.id for t in candidates])
    sent: list[Task] = []
    for task in candidates:
        if task.id in already:
            continue
        planned = planned_reminder_at(task.due_at, window, rules.get(int(task.id)))
        if planned is None or planned > moment:
            continue
        recipients = await hr_tasks.assignees(session, task)
        await _deliver(
            session,
            bot=bot,
            employees=recipients,
            kind=hr_notify.KIND_TASK_DEADLINE,
            text=f"⏳ Напоминание: {hr_notify.task_short(task)} — срок "
            f"{hr_notify.fmt_due(task.due_at)}",
            payload={"task_id": task.id},
        )
        session.add(
            TaskEvent(
                task_id=task.id,
                from_status=task.status,
                to_status=task.status,
                by_employee_id=None,
                comment=REMINDER_EVENT_COMMENT,
            )
        )
        sent.append(task)
    if sent:
        await session.commit()
    return sent


async def _overdue_since(
    session: AsyncSession, task_ids: list[int]
) -> dict[int, datetime]:
    """Когда каждая задача стала просроченной (по событиям, без новой колонки)."""
    if not task_ids:
        return {}
    rows = (
        await session.execute(
            select(TaskEvent.task_id, func.max(TaskEvent.at))
            .where(
                TaskEvent.task_id.in_(task_ids),
                TaskEvent.to_status == TASK_OVERDUE,
            )
            .group_by(TaskEvent.task_id)
        )
    ).all()
    return {int(task_id): at for task_id, at in rows if at is not None}


async def _second_escalated_at(
    session: AsyncSession, task_ids: list[int]
) -> dict[int, datetime]:
    """Когда по задаче последний раз писали админам (маркер-событие)."""
    if not task_ids:
        return {}
    rows = (
        await session.execute(
            select(TaskEvent.task_id, func.max(TaskEvent.at))
            .where(
                TaskEvent.task_id.in_(task_ids),
                TaskEvent.comment == SECOND_EVENT_COMMENT,
            )
            .group_by(TaskEvent.task_id)
        )
    ).all()
    return {int(task_id): at for task_id, at in rows if at is not None}


@dataclass(frozen=True)
class EscalationCandidate:
    """Судьба одной просроченной задачи на второй ступени.

    `reason` — почему она ещё не улетела админам: `ready` (уже пора),
    `waiting` (ждём порог), `sent` (писали в этом цикле), `silenced`
    (руководитель сказал «решено»/«завтра»), `demo` (тестовый пул).
    """

    task_id: int
    title: str
    due_at: datetime | None
    overdue_since: datetime | None
    hours_overdue: int
    hours_left: int
    ready: bool
    reason: str


@dataclass(frozen=True)
class EscalationPlan:
    """Сухой прогон: что случится на следующем тике."""

    enabled: bool
    hours: int
    admins: int
    items: list[EscalationCandidate]
    # Повтор в каждой смене, пока задача висит (а не раз за цикл).
    repeat_per_shift: bool = False

    @property
    def ready(self) -> list[EscalationCandidate]:
        return [item for item in self.items if item.ready]


async def escalation_plan(
    session: AsyncSession, *, now: datetime | None = None
) -> EscalationPlan:
    """Посчитать вторую ступень, НИЧЕГО не отправляя и не записывая.

    Это тот же код, что реально шлёт уведомления: сначала строим список с
    причинами, потом отправляем только `ready`. Иначе «сухой прогон» врал бы.
    """
    moment = now or datetime.now(UTC)
    hours = await hr_settings.get_second_escalation_hours(session)
    repeat = await hr_settings.get_second_escalation_repeat(session)
    enabled = await hr_settings.get_escalation_enabled(
        session
    ) and await hr_settings.get_second_escalation_enabled(session)
    admin_list = await admins(session)

    # Тестовый пул исключаем ВСЕГДА, даже когда он виден в интерфейсе: иначе
    # админы получали бы алерты про [BOT]-задачи, которые никогда не закроют.
    demo_ids = await hr_demo.demo_employee_ids(session)
    sim_ids = {
        int(v)
        for v in (await session.scalars(_simulation_employee_ids())).all()
    }
    tasks = [
        task
        for task in (
            await session.scalars(
                select(Task).where(Task.status == TASK_OVERDUE).limit(BATCH_LIMIT)
            )
        ).all()
        if task.assignee_employee_id not in demo_ids
        and task.assignee_employee_id not in sim_ids
    ]
    if not tasks:
        return EscalationPlan(
            enabled=enabled,
            hours=hours,
            admins=len(admin_list),
            items=[],
            repeat_per_shift=repeat,
        )

    ids = [int(task.id) for task in tasks]
    since_map = await _overdue_since(session, ids)
    sent_map = await _second_escalated_at(session, ids)
    state_map = await hr_alerts.states(session, ids)

    items: list[EscalationCandidate] = []
    for task in tasks:
        since = since_map.get(int(task.id))
        elapsed = (moment - _aware(since)) if since else timedelta(0)
        elapsed_hours = elapsed.total_seconds() / 3600
        left = max(0, math.ceil(hours - elapsed_hours))
        silenced = (state_map.get(int(task.id)) or hr_alerts.AlertState()).silenced(moment)
        if marker_covers_cycle(
            sent_map.get(int(task.id)),
            since,
            repeat_per_shift=repeat,
            now=moment,
        ):
            reason = "sent"
        elif silenced:
            reason = "silenced"
        elif since is None:
            reason = "unknown"
        elif second_escalation_due(
            status=task.status, overdue_since=since, now=moment, hours=hours
        ):
            reason = "ready"
        else:
            reason = "waiting"
        items.append(
            EscalationCandidate(
                task_id=int(task.id),
                title=task.title,
                due_at=task.due_at,
                overdue_since=since,
                hours_overdue=int(elapsed_hours),
                hours_left=left,
                ready=reason == "ready" and enabled and bool(admin_list),
                reason=reason,
            )
        )

    return EscalationPlan(
        enabled=enabled,
        hours=hours,
        admins=len(admin_list),
        items=items,
        repeat_per_shift=repeat,
    )


def format_plan(plan: EscalationPlan, *, limit: int = 5) -> str:
    """Текст сухого прогона для бота: готовые сверху, ожидающие — с таймером."""
    lines = ["🔭 <b>Вторая ступень: сухой прогон</b>", ""]
    if not plan.enabled:
        lines.append("Вторая ступень выключена в настройках.")
        return "\n".join(lines)
    if plan.admins == 0:
        lines.append("Нет активных администраторов — отправлять некому.")
        return "\n".join(lines)

    ready = plan.ready
    waiting = [item for item in plan.items if item.reason == "waiting"]
    lines.append(
        f"Порог: {plan.hours} ч · админов: {plan.admins} · "
        f"к отправке сейчас: <b>{len(ready)}</b>"
    )
    if plan.repeat_per_shift:
        lines.append("Повтор: в каждой смене, пока задача висит.")
    for item in ready[:limit]:
        lines.append(f"🚨 «{item.title}» — просрочено {item.hours_overdue} ч, пора")
    if len(ready) > limit:
        lines.append(f"…и ещё {len(ready) - limit}")

    if waiting:
        lines.append("")
        lines.append("<b>Ждут порога</b>")
        waiting.sort(key=lambda item: item.hours_left)
        for item in waiting[:limit]:
            lines.append(
                f"⏳ «{item.title}» — через {item.hours_left} ч "
                f"(просрочено {item.hours_overdue} ч)"
            )
        if len(waiting) > limit:
            lines.append(f"…и ещё {len(waiting) - limit}")

    if not plan.items:
        lines.append("Просроченных задач вне тестового пула нет.")
    else:
        parked = len(plan.items) - len(ready) - len(waiting)
        if parked:
            lines.append("")
            lines.append(
                f"Не побеспокоят: {parked} (уже отправлено / решено / отложено / без даты)"
            )
    lines.append("")
    lines.append("Ничего не отправлено — это только прогноз.")
    return "\n".join(lines)


async def escalate_to_admins(
    session: AsyncSession,
    *,
    bot=None,  # noqa: ANN001
    now: datetime | None = None,
) -> list[Task]:
    """Вторая ступень: напомнить админам о просрочке без реакции руководителя.

    Считает тот же `escalation_plan`, что показывает сухой прогон, и отправляет
    только готовые пункты. Читаем все задачи в `overdue` (а не только свежие):
    ступень срабатывает по таймеру, а не по моменту перехода.

    Молчание руководителя уважаем: если он нажал «решено» или «напомнить
    завтра» (`hr_alerts`), задача затихает до указанного момента — второй
    ступенью его решение не отменяем.
    """
    plan = await escalation_plan(session, now=now)
    if not plan.enabled or plan.admins == 0:
        # Без админов не отправляем и НЕ ставим маркер: когда админ появится,
        # просрочка всё ещё должна до него дойти.
        return []
    due = plan.ready
    if not due:
        return []

    recipients = await admins(session)
    tasks_by_id = {
        int(task.id): task
        for task in (
            await session.scalars(
                select(Task).where(Task.id.in_([item.task_id for item in due]))
            )
        ).all()
    }

    for item in due:
        task = tasks_by_id.get(item.task_id)
        if task is None:
            continue
        await _deliver(
            session,
            bot=bot,
            employees=recipients,
            kind=hr_notify.KIND_TASK_ESCALATED,
            text=hr_notify.second_escalation_text(
                item.title, item.due_at, hours=plan.hours
            ),
            payload={"task_id": task.id},
            keyboard=hr_alerts.alert_keyboard(int(task.id)),
        )
        session.add(
            TaskEvent(
                task_id=task.id,
                from_status=TASK_OVERDUE,
                to_status=TASK_OVERDUE,
                by_employee_id=None,
                comment=SECOND_EVENT_COMMENT,
            )
        )
    await session.commit()
    return [tasks_by_id[item.task_id] for item in due if item.task_id in tasks_by_id]


async def escalate_overdue(
    session: AsyncSession,
    *,
    bot=None,  # noqa: ANN001
    now: datetime | None = None,
) -> list[Task]:
    """Пометить просроченные и уведомить руководителей. Возвращает задачи.

    Поручения, по которым руководитель уже нажал «решено» или «напомнить
    завтра», пропускаем: именно из-за отсутствия такого выхода бот и будил
    управляющего повторно. Статус при этом не откатываем — задача остаётся
    просроченной в отчётах и кабинете.
    """
    moment = now or datetime.now(UTC)
    changed = await hr_tasks.sweep_overdue(session, now=moment)
    if not changed:
        return []
    state_map = await hr_alerts.states(session, [int(t.id) for t in changed])
    active = hr_alerts.filter_silenced(changed, state_map, moment)
    if not active:
        await session.commit()
        return []
    changed = active
    recipients_base = await managers(session)
    for task in changed:
        creator = (
            await session.get(Employee, task.created_by_employee_id)
            if task.created_by_employee_id
            else None
        )
        recipients = escalation_recipients(managers=recipients_base, creator=creator)
        await _deliver(
            session,
            bot=bot,
            employees=recipients,
            kind=hr_notify.KIND_TASK_OVERDUE,
            text=hr_notify.task_overdue_text(task),
            payload={"task_id": task.id},
            # Кнопки прямо в алерте: ответить можно, не заходя в приложение.
            keyboard=hr_alerts.alert_keyboard(int(task.id)),
        )
    await session.commit()
    return changed


async def run_hr_tick(*, bot=None, now: datetime | None = None) -> dict:  # noqa: ANN001
    """Тело job'а планировщика: напоминания + эскалация. Идемпотентно."""
    from app.db.base import get_sessionmaker

    sm = get_sessionmaker()
    reminders = 0
    escalated = 0
    escalated_second = 0
    purged = 0
    try:
        async with sm() as session:
            # Корзина уволенных: через 30 дней данные сносим сами, чтобы
            # обещание «автоудалится» не зависело от чьей-то памяти.
            from app.services import hr_admin_ops

            purged = await hr_admin_ops.purge_due(session, now=now)
            if await hr_settings.get_reminders_enabled(session):
                reminders = len(
                    await send_deadline_reminders(session, bot=bot, now=now)
                )
            if await hr_settings.get_escalation_enabled(session):
                escalated = len(await escalate_overdue(session, bot=bot, now=now))
                # Вторая ступень идёт после первой: только что просроченные
                # задачи не должны сразу пинговать админов.
                escalated_second = len(
                    await escalate_to_admins(session, bot=bot, now=now)
                )
    except Exception as exc:  # noqa: BLE001 — job не имеет права падать
        log.warning("hr.tick_failed", error=str(exc))
    if reminders or escalated or escalated_second or purged:
        log.info(
            "hr.tick_done",
            reminders=reminders,
            escalated=escalated,
            escalated_second=escalated_second,
            purged=purged,
        )
    return {
        "reminders": reminders,
        "escalated": escalated,
        "escalated_second": escalated_second,
        "purged": purged,
    }
