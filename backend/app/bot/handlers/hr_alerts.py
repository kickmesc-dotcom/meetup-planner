"""Кнопки под алертами руководителя: «решено», «напомнить завтра», «мьют».

Отдельный роутер, потому что это не часть сценария сотрудника: сюда приходят
нажатия из сообщений, которые бот отправил руководителю в личку планировщиком
(`services/hr_reminders.py`).

Права проверяются здесь же: кнопка видна только в личке руководителя, но
callback-данные можно подделать, поэтому перед любым действием проверяем, что
нажавший — активный `aup`/`admin`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy import select

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.hr_models import Task
from app.db.models import User
from app.services import hr_access, hr_alerts, hr_settings

log = structlog.get_logger()
router = Router(name="hr-alerts")


async def _answer(callback: CallbackQuery, text: str, *, alert: bool = False) -> None:
    try:
        await callback.answer(text, show_alert=alert)
    except TelegramBadRequest:  # протухший callback — не наша проблема
        log.info("hr.alerts.answer_failed", data=callback.data)


async def _append_note(callback: CallbackQuery, note: str) -> None:
    """Дописать пометку в исходное сообщение и снять клавиатуру.

    Best-effort: сообщение могло быть удалено или устареть, а действие уже
    выполнено — падать из-за косметики нельзя.
    """
    message = callback.message
    text = getattr(message, "text", None) or getattr(message, "caption", None)
    if message is None or not text or note in text:
        return
    try:
        await message.edit_text(f"{text}\n\n{note}", reply_markup=None)
    except TelegramBadRequest as exc:
        log.info("hr.alerts.edit_failed", error=str(exc))


async def _manager(callback: CallbackQuery):  # noqa: ANN202 — Employee | None
    """Нажавший, если он активный руководитель/админ. Иначе None."""
    user = callback.from_user
    if user is None:
        return None, None
    sm = get_sessionmaker()
    async with sm() as session:
        owner = await session.scalar(select(User).where(User.telegram_id == user.id))
        if owner is None:
            return None, None
        employee = await hr_access.get_employee(session, owner.id)
        if employee is None or not employee.is_active or not hr_access.is_aup(employee):
            return session, None
        return session, employee


@router.callback_query(F.data.startswith(f"{hr_alerts.CALLBACK_PREFIX}:"))
async def on_alert_action(callback: CallbackQuery) -> None:
    action = hr_alerts.parse_callback(callback.data)
    if action is None:
        await _answer(callback, "Кнопка устарела")
        return

    session, employee = await _manager(callback)
    if session is None:
        await _answer(callback, "Нет доступа", alert=True)
        return
    if employee is None:
        await _answer(callback, "Управлять алертами может только руководитель", alert=True)
        return

    try:
        if action.action == hr_alerts.ACTION_MUTE:
            hours = action.hours or 24
            until = await hr_settings.mute_for_hours(session, hours)
            local = until.astimezone(ZoneInfo(get_settings().scheduler_tz))
            log.info("hr.alerts.muted", hours=hours, by=employee.id)
            await _answer(callback, f"Тишина до {local:%d.%m %H:%M}")
            await _append_note(callback, f"🔕 Мьют на {hours} ч — до {local:%d.%m %H:%M}")
            return

        task_id = action.task_id or 0
        task = await session.get(Task, task_id)
        if task is None:
            await _answer(callback, "Поручение не найдено", alert=True)
            return

        if action.action == hr_alerts.ACTION_RESOLVE:
            await hr_alerts.mark_resolved(session, task, by=employee)
            await session.commit()
            log.info("hr.alerts.resolved", task_id=task_id, by=employee.id)
            await _answer(callback, "Больше не алертим по этому поручению")
            await _append_note(callback, "✅ Отмечено как решённое — алерты остановлены")
            return

        if action.action == hr_alerts.ACTION_TOMORROW:
            opens_at = await hr_settings.get_work_open(session)
            until = hr_alerts.next_shift_morning(
                datetime.now(UTC),
                opens_at=opens_at,
                tz=ZoneInfo(get_settings().scheduler_tz),
            )
            await hr_alerts.snooze(session, task, until, by=employee)
            await session.commit()
            local = until.astimezone(ZoneInfo(get_settings().scheduler_tz))
            log.info("hr.alerts.snoozed", task_id=task_id, until=local.isoformat())
            await _answer(callback, f"Напомню {local:%d.%m в %H:%M}")
            await _append_note(callback, f"⏰ Отложено до {local:%d.%m %H:%M}")
    finally:
        await session.close()
