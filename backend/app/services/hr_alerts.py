"""Кнопки управления алертами в сообщении бота.

Боль управляющего была конкретной: бот честно будил его в 03:41 по поручениям,
которые он сам же и «понажимал» в тестовом пуле. Рабочие часы (`hr_settings`)
решают половину задачи — вторую половину решает возможность ответить прямо в
сообщении, не заходя в приложение:

* **«Ситуация решена»** — по этому поручению алерты руководителю больше не идут;
* **«Напомнить завтра»** — тишина до утра следующей смены;
* **мьют 24 ч / 3 суток / неделю / месяц** — тишина по всем алертам.

Мьют живёт в настройках (`hr_settings`), а «решено»/«напомнить» — маркерами в
`task_events` с комментарием. Отдельных колонок не заводим сознательно: история
поручения и так пишется, а идемпотентность получается бесплатной — повторное
нажатие просто добавляет ещё один маркер, состояние читается по последнему.

Важно: заглушается только доставка руководителю. Сотрудник продолжает видеть
поручение (и напоминание о сроке) — «ситуация решена» не отменяет работу.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import Employee, Task, TaskEvent

# Маркеры в `task_events.comment`.
COMMENT_RESOLVED = "alert_resolved"
COMMENT_SNOOZE_PREFIX = "alert_snooze:"

# Префикс callback-данных всех кнопок алертов (одно место — легко опознать своё).
CALLBACK_PREFIX = "hra"

ACTION_RESOLVE = "resolve"
ACTION_TOMORROW = "tomorrow"
ACTION_MUTE = "mute"

# Варианты мьюта: (подпись на кнопке, часов вперёд).
MUTE_CHOICES: tuple[tuple[str, int], ...] = (
    ("24 ч", 24),
    ("3 суток", 72),
    ("7 дней", 168),
    ("30 дней", 720),
)

_SNOOZE_RE = re.compile(r"^alert_snooze:(?P<stamp>.+)$")


@dataclass(frozen=True)
class AlertState:
    """Что известно про алерты по одному поручению."""

    resolved: bool = False
    snoozed_until: datetime | None = None

    def silenced(self, now: datetime) -> bool:
        moment = now if now.tzinfo else now.replace(tzinfo=UTC)
        if self.resolved:
            return True
        if self.snoozed_until is None:
            return False
        until = (
            self.snoozed_until
            if self.snoozed_until.tzinfo
            else self.snoozed_until.replace(tzinfo=UTC)
        )
        return moment < until


def snooze_comment(until: datetime) -> str:
    moment = until if until.tzinfo else until.replace(tzinfo=UTC)
    return f"{COMMENT_SNOOZE_PREFIX}{moment.astimezone(UTC).isoformat()}"


def parse_snooze(comment: str | None) -> datetime | None:
    """Дата из маркера `alert_snooze:<iso>`; мусор → None, а не исключение."""
    if not comment:
        return None
    match = _SNOOZE_RE.match(comment.strip())
    if not match:
        return None
    try:
        value = datetime.fromisoformat(match.group("stamp").replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def state_from_comments(comments: Iterable[str | None]) -> AlertState:
    """Собрать состояние по комментариям событий задачи.

    «Решено» сильнее отсрочки: если руководитель один раз сказал «вопрос
    закрыт», поздний мьют уже ничего не меняет.
    """
    resolved = False
    snoozed_until: datetime | None = None
    for comment in comments:
        if comment == COMMENT_RESOLVED:
            resolved = True
            continue
        stamp = parse_snooze(comment)
        if stamp is not None and (snoozed_until is None or stamp > snoozed_until):
            snoozed_until = stamp
    return AlertState(resolved=resolved, snoozed_until=snoozed_until)


def next_shift_morning(
    now: datetime, *, opens_at: time, tz: ZoneInfo
) -> datetime:
    """Утро следующей смены: завтра в час открытия ресторана (в его таймзоне)."""
    local = (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(tz)
    tomorrow = (local + timedelta(days=1)).date()
    return datetime.combine(tomorrow, opens_at, tzinfo=tz)


def cb_resolve(task_id: int) -> str:
    return f"{CALLBACK_PREFIX}:{ACTION_RESOLVE}:{task_id}"


def cb_tomorrow(task_id: int) -> str:
    return f"{CALLBACK_PREFIX}:{ACTION_TOMORROW}:{task_id}"


def cb_mute(hours: int) -> str:
    return f"{CALLBACK_PREFIX}:{ACTION_MUTE}:{hours}"


@dataclass(frozen=True)
class Action:
    action: str
    task_id: int | None = None
    hours: int | None = None


def parse_callback(data: str | None) -> Action | None:
    """Разобрать callback-данные кнопки. Чужое/битое → None."""
    if not data:
        return None
    parts = data.split(":")
    if len(parts) < 2 or parts[0] != CALLBACK_PREFIX:
        return None
    action = parts[1]
    if action == ACTION_MUTE:
        if len(parts) != 3 or not parts[2].isdigit():
            return None
        hours = int(parts[2])
        if hours not in {value for _, value in MUTE_CHOICES}:
            return None
        return Action(action=action, hours=hours)
    if action in {ACTION_RESOLVE, ACTION_TOMORROW}:
        if len(parts) != 3 or not parts[2].isdigit():
            return None
        return Action(action=action, task_id=int(parts[2]))
    return None


# --------------------------------------------------------------------------
# Состояние по данным (без своих колонок — только маркеры в истории)
# --------------------------------------------------------------------------


async def states(
    session: AsyncSession, task_ids: Iterable[int]
) -> dict[int, AlertState]:
    """Состояние алертов для пачки задач одним запросом.

    Порядок комментариев не важен: `state_from_comments` сам решает, что
    сильнее (решено > отсрочка), а повторные маркеры просто дублируют вывод.
    """
    ids = [int(t) for t in task_ids]
    if not ids:
        return {}
    rows = await session.execute(
        select(TaskEvent.task_id, TaskEvent.comment).where(TaskEvent.task_id.in_(ids))
    )
    grouped: dict[int, list[str | None]] = {}
    for task_id, comment in rows.all():
        grouped.setdefault(int(task_id), []).append(comment)
    return {task_id: state_from_comments(items) for task_id, items in grouped.items()}


def filter_silenced(
    tasks: Iterable[Task], state_map: dict[int, AlertState], now: datetime
) -> list[Task]:
    """Оставить только те поручения, по которым алертить ещё нужно."""
    return [
        task
        for task in tasks
        if not (state_map.get(int(task.id)) or AlertState()).silenced(now)
    ]


def _marker(task: Task, *, comment: str, by: Employee | None) -> TaskEvent:
    """Событие-маркер: статус не меняем, историю не искажаем."""
    return TaskEvent(
        task_id=task.id,
        from_status=task.status,
        to_status=task.status,
        by_employee_id=by.id if by is not None else None,
        comment=comment,
    )


async def mark_resolved(
    session: AsyncSession, task: Task, *, by: Employee | None = None
) -> None:
    """«Ситуация решена»: алерты руководителю по этому поручению выключаются."""
    session.add(_marker(task, comment=COMMENT_RESOLVED, by=by))


async def snooze(
    session: AsyncSession, task: Task, until: datetime, *, by: Employee | None = None
) -> None:
    """«Напомнить завтра»: тишина до указанного момента."""
    session.add(_marker(task, comment=snooze_comment(until), by=by))


def alert_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Клавиатура под алертом: решено / напомнить завтра / мьют."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ситуация решена, больше не алертить",
                    callback_data=cb_resolve(task_id),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏰ Напомнить завтра",
                    callback_data=cb_tomorrow(task_id),
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔕 Мьют {label}", callback_data=cb_mute(hours)
                )
                for label, hours in MUTE_CHOICES
            ],
        ]
    )
