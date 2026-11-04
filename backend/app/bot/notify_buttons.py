"""Кнопки под автоматическими уведомлениями: «Отключить» и «Настройки».

Правило, которое здесь закреплено: у любого автоматического сообщения в
Telegram должна быть возможность выключить его **из самого сообщения**, не
разыскивая настройки по приложению. Человек, которому сводка не нужна, не
должен писать в поддержку — и не должен терпеть.

Вторая кнопка ведёт в приложение: отключение кнопкой — быстрое действие, а
настройки — место, где видно, что ещё включено (иначе человек выключит одно,
а через неделю получит другое).

Почему callback, а не ссылка. `callback_data` не требует, чтобы у сообщения был
публичный URL, и работает в личке; переход в приложение — отдельная кнопка
`web_app`.
"""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from sqlalchemy import select

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import User
from app.services import hr_access, notify_prefs

log = structlog.get_logger()
router = Router(name="notify-prefs")

CALLBACK_PREFIX = "np"

# Подписи кнопок зависят от состояния: «Отключить» на выключенном сообщении
# было бы ложью, а «Включить» на включённом — ловушкой.
TEXT_ON = "Отключить"
TEXT_OFF = "Включить"
TEXT_SETTINGS = "Настройки"


def keyboard(
    kind: str = "digest",
    *,
    enabled: bool = True,
    app_url: str | None = None,
) -> InlineKeyboardMarkup:
    url = app_url or get_settings().mini_app_url
    action = "off" if enabled else "on"
    rows = [
        [
            InlineKeyboardButton(
                text=TEXT_ON if enabled else TEXT_OFF,
                callback_data=f"{CALLBACK_PREFIX}:{kind}:{action}",
            ),
            InlineKeyboardButton(
                text=TEXT_SETTINGS, web_app=WebAppInfo(url=url)
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _answer(callback: CallbackQuery, text: str, *, alert: bool = False) -> None:
    try:
        await callback.answer(text, show_alert=alert)
    except TelegramBadRequest:
        log.info("notify.answer_failed", data=callback.data)


@router.callback_query(F.data.startswith(f"{CALLBACK_PREFIX}:"))
async def on_notify_toggle(callback: CallbackQuery) -> None:
    """Включить/выключить личную подписку из-под сообщения."""
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await _answer(callback, "Кнопка устарела")
        return
    kind, action = parts[1], parts[2]
    if action not in {"on", "off"}:
        await _answer(callback, "Кнопка устарела")
        return

    tg_user = callback.from_user
    if tg_user is None:
        await _answer(callback, "Нет доступа", alert=True)
        return

    sm = get_sessionmaker()
    async with sm() as session:
        owner = await session.scalar(
            select(User).where(User.telegram_id == tg_user.id)
        )
        if owner is None:
            await _answer(callback, "Нет доступа", alert=True)
            return
        employee = await hr_access.get_employee(session, owner.id)
        if employee is None or not employee.is_active:
            await _answer(callback, "Нет доступа", alert=True)
            return
        try:
            enabled = await notify_prefs.set_enabled(
                session,
                org_id=int(employee.org_id),
                user_id=int(owner.id),
                kind=kind,
                enabled=action == "on",
            )
        except notify_prefs.NotifyPrefError:
            await _answer(callback, "Кнопка устарела")
            return
        await session.commit()

    if enabled:
        await _answer(callback, "Включено")
    else:
        await _answer(callback, "Выключено")

    # Клавиатуру меняем, а не удаляем: человек может передумать сразу же.
    message = callback.message
    if message is not None:
        try:
            await message.edit_reply_markup(
                reply_markup=keyboard(kind, enabled=enabled)
            )
        except TelegramBadRequest as exc:  # сообщение могли удалить
            log.info("notify.edit_failed", error=str(exc))

    log.info(
        "notify.pref_changed",
        kind=kind,
        enabled=enabled,
        employee_id=int(employee.id),
    )


__all__ = ["CALLBACK_PREFIX", "keyboard", "router"]
