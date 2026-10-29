"""Устаревшие кнопки бота (план, 12.1).

Живой случай: в чате висело меню прошлой сборки, человек нажимал «Полезные
ссылки» — и ничего. В логах Amvera при этом было
`Update id=… is not handled`: апдейт дошёл, вебхук ответил `200`, но фильтр
`F.data == "hr:links"` не совпал, потому что в старом сообщении лежит другое
`callback_data`. Telegram уже отправленные сообщения не переписывает, поэтому
такие кнопки могут жить в чате месяцами.

Здесь проверяем поведение ловушки, а не базу: сессия и загрузка сотрудника
подменены. Проверяем оба исхода — есть сотрудник (показываем текущее меню) и
нет (единственный рабочий вход — `/start`).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.bot.handlers import hr_bot


class _Session:
    def __init__(self, user: object | None = None) -> None:
        self._user = user

    async def get(self, model: object, pk: object) -> object:
        return self._user

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _employee() -> SimpleNamespace:
    return SimpleNamespace(
        role="employee",
        badge=None,
        badge_emoji=None,
        is_demo=False,
        department_id=1,
        user_id=1,
    )


def _callback(data: str = "old:links") -> MagicMock:
    callback = MagicMock()
    callback.from_user = SimpleNamespace(id=777)
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    return callback


def _patch_common(monkeypatch, *, user=None, employee=None) -> None:
    async def fake_load(session, telegram_id):  # noqa: ANN001
        if employee is None:
            return None
        return SimpleNamespace(display_name="Сергей"), employee

    async def fake_department(session, department_id):  # noqa: ANN001
        return "Зал"

    monkeypatch.setattr(hr_bot, "_load", fake_load)
    monkeypatch.setattr(hr_bot, "_department_name", fake_department)
    monkeypatch.setattr(
        hr_bot, "get_sessionmaker", lambda: (lambda: _Session(user))
    )


async def test_stale_button_shows_current_menu(monkeypatch):
    _patch_common(
        monkeypatch,
        user=SimpleNamespace(display_name="Сергей"),
        employee=_employee(),
    )
    callback = _callback()

    await hr_bot.on_stale_callback(callback)

    callback.answer.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    text = callback.message.edit_text.await_args.args[0]
    # Человек понимает, почему меню сменилось, а не видит «магию».
    assert "прошлой версии меню" in text
    assert "Выбери раздел" in text
    # Кнопки — текущие: следующее нажатие уже сработает.
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    datas = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "hr:links" in datas


async def test_stale_button_without_employee_names_start(monkeypatch):
    _patch_common(monkeypatch, employee=None)
    callback = _callback()

    await hr_bot.on_stale_callback(callback)

    callback.answer.assert_awaited_once()
    assert "/start" in callback.answer.await_args.args[0]
    # Меню некому показать — сообщение не трогаем.
    callback.message.edit_text.assert_not_awaited()
