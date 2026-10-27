"""Утренняя сводка руководителю (план, 8.2).

Зачем отдельный сервис, а не ещё одна строка в тике напоминаний. Руководителю
нужен один короткий ответ на вопрос «что сегодня требует меня», собранный из
четырёх источников: поручения, смены, чек-листы и проблемы. Собирать это глазами
по четырём экранам — работа, которую приложение может сделать само, а писать
раз в день по одному событию — шум.

Правила, которые здесь важны:

* **Сводка — числовая.** Никаких «оценок» и процентов: руководитель за минуту
  видит «3 просрочено / 2 не открыли / 4 проблемы» и решает, идти ли в детали.
  Детали — на экранах, у которых есть свои фильтры.
* **Права как у экранов.** Считаем через те же правила видимости, что журнал
  проблем (`hr_issues.summary`), поэтому сводка не становится обходным путём к
  чужим данным.
* **Однократность в сутки.** Планировщик может перезапуститься, тик может
  сработать дважды — отметка `hr.digest:last_sent` не даёт прислать одно и то же
  утро дважды.
* **Пустая сводка — не молчание.** Если всё спокойно, сообщение всё равно
  приходит: «всё спокойно» — это тоже ответ, а тишина читается как «бот сломался».
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    ROLE_ADMIN,
    ROLE_AUP,
    RUN_IN_PROGRESS,
    SHIFT_PLANNED,
    SHIFT_WORKED,
    TASK_OVERDUE,
    ChecklistRun,
    Employee,
    HrShift,
    Task,
)
from app.db.models import User
from app.services import hr_issues, hr_settings

log = structlog.get_logger(__name__)

# Сколько заголовков просроченных поручений показывать в сообщении. Больше —
# уже не сводка, а список; полный список открывается в приложении.
MAX_TITLES = 3


@dataclass(frozen=True)
class Digest:
    """Один утренний срез. Числа — то, что руководитель читает первым."""

    day: date
    overdue_tasks: int
    overdue_titles: tuple[str, ...]
    planned_today: int
    not_started: int
    open_runs: int
    problems_open: int
    problems_attention: int

    @property
    def calm(self) -> bool:
        """Ничего не требует внимания: можно сказать это словами."""
        return (
            self.overdue_tasks == 0
            and self.not_started == 0
            and self.problems_attention == 0
            and self.open_runs == 0
        )


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение числительных — без него «3 поручение» выглядит как баг."""
    tail = count % 100
    if 11 <= tail <= 14:
        return many
    tail = count % 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


async def build(
    session: AsyncSession,
    employee: Employee,
    *,
    today: date | None = None,
) -> Digest:
    """Собрать сводку для конкретного руководителя (права — как у журнала)."""
    day = today or hr_settings.local_now().date()

    overdue = int(
        await session.scalar(
            select(func.count()).select_from(Task).where(Task.status == TASK_OVERDUE)
        )
        or 0
    )
    titles_rows = await session.scalars(
        select(Task.title)
        .where(Task.status == TASK_OVERDUE)
        .order_by(Task.due_at.asc().nulls_last(), Task.id.asc())
        .limit(MAX_TITLES)
    )
    titles = tuple(str(item) for item in titles_rows.all())

    # Смены на сегодня без единого прогона чек-листа: «зал не открыли».
    # Считаем только живых и не тестовых: пул демо не должен портить утреннюю
    # картину, иначе руководитель привыкнет игнорировать сводку.
    planned_today = int(
        await session.scalar(
            select(func.count())
            .select_from(HrShift)
            .join(Employee, Employee.id == HrShift.employee_id)
            .where(
                HrShift.day == day,
                HrShift.status.in_((SHIFT_PLANNED, SHIFT_WORKED)),
                Employee.is_active.is_(True),
                Employee.is_simulation.is_(False),
            )
        )
        or 0
    )
    started_count = int(
        await session.scalar(
            select(func.count(func.distinct(ChecklistRun.employee_id)))
            .select_from(ChecklistRun)
            .join(Employee, Employee.id == ChecklistRun.employee_id)
            .where(
                ChecklistRun.shift_date == day,
                Employee.is_active.is_(True),
                Employee.is_simulation.is_(False),
            )
        )
        or 0
    )
    not_started = max(0, planned_today - started_count) if planned_today else 0

    open_runs = int(
        await session.scalar(
            select(func.count())
            .select_from(ChecklistRun)
            .where(
                ChecklistRun.shift_date == day,
                ChecklistRun.status == RUN_IN_PROGRESS,
            )
        )
        or 0
    )

    summary = await hr_issues.summary(session, employee)

    return Digest(
        day=day,
        overdue_tasks=overdue,
        overdue_titles=titles,
        planned_today=planned_today,
        not_started=not_started,
        open_runs=open_runs,
        problems_open=int(summary.get("total_open", 0)),
        problems_attention=int(summary.get("attention", 0)),
    )


def message(digest: Digest, *, app_url: str | None = None) -> str:
    """Текст для Telegram. Короткий: руководитель читает его на ходу."""
    lines = [f"Сводка на {digest.day.strftime('%d.%m')}"]

    if digest.calm:
        lines.append("Всё спокойно: просрочек и срочных проблем нет.")
    else:
        if digest.overdue_tasks:
            word = _plural(digest.overdue_tasks, "поручение", "поручения", "поручений")
            lines.append(f"Просрочено: {digest.overdue_tasks} {word}")
            for title in digest.overdue_titles:
                lines.append(f"  • {title}")
        if digest.not_started:
            word = _plural(digest.not_started, "смена", "смены", "смен")
            lines.append(
                f"Не открыли чек-лист: {digest.not_started} {word} "
                f"из {digest.planned_today}"
            )
        if digest.open_runs:
            word = _plural(digest.open_runs, "чек-лист", "чек-листа", "чек-листов")
            lines.append(f"В работе сейчас: {digest.open_runs} {word}")
        if digest.problems_open:
            word = _plural(digest.problems_open, "проблема", "проблемы", "проблем")
            tail = (
                f", срочных: {digest.problems_attention}"
                if digest.problems_attention
                else ""
            )
            lines.append(f"Открыто проблем: {digest.problems_open} {word}{tail}")

    if app_url:
        lines.append(app_url)
    return "\n".join(lines)


async def _manager_tg_ids(session: AsyncSession, managers: list[Employee]) -> dict[int, int]:
    """user_id → telegram_id. Без этого личка не отправится даже при живом боте."""
    if not managers:
        return {}
    rows = await session.execute(
        select(Employee.user_id, User.telegram_id)
        .join(User, User.id == Employee.user_id)
        .where(Employee.id.in_([m.id for m in managers]))
    )
    return {int(user_id): int(tg_id) for user_id, tg_id in rows.all()}


async def send_morning(
    session: AsyncSession,
    *,
    bot=None,  # noqa: ANN001
    now: datetime | None = None,
    app_url: str | None = None,
    force: bool = False,
) -> int:
    """Отправить сводку всем руководителям. Возвращает число сообщений в личку.

    `force` нужен ручной проверке из админки: без него повторный вызов в тот же
    день ничего не делает (идемпотентность важнее «пусть придёт ещё раз»).
    """
    if not force and not await hr_settings.get_digest_enabled(session):
        return 0

    day = (now or hr_settings.local_now()).date()
    if not force and await hr_settings.get_digest_sent_on(session) == day:
        return 0

    from app.services import hr_reminders  # локально: hr_reminders сам зовёт нас

    managers = [
        item
        for item in await hr_reminders.managers(session)
        if item.role in (ROLE_AUP, ROLE_ADMIN)
    ]
    if not managers:
        return 0

    tg_ids = await _manager_tg_ids(session, managers)
    sent = 0
    for manager in managers:
        # Сводка персональная: у руководителя подразделения журнал проблем
        # фильтруется по его отделу, и числа обязаны совпадать с тем, что он
        # увидит на экране.
        digest = await build(session, manager, today=day)
        text = message(digest, app_url=app_url)
        tg_id = tg_ids.get(int(manager.user_id))
        if tg_id and bot is not None:
            try:
                await bot.send_message(chat_id=tg_id, text=text)
                sent += 1
            except Exception as exc:  # noqa: BLE001 — один менеджер не блокирует остальных
                log.warning("hr.digest_dm_failed", employee_id=manager.id, error=str(exc))

    await hr_settings.set_digest_sent_on(session, day)
    log.info("hr.digest_sent", day=day.isoformat(), managers=len(managers), dm=sent)
    return sent
