"""SemiTaskBot: весь рабочий чат-интерфейс в личке бота.

Почему одним модулем. Это один связный сценарий с общим состоянием (сотрудник →
меню → задача → фото), и держать его в пяти файлах с перекрёстными импортами
дороже, чем прочитать сверху вниз. Разделы помечены комментариями:

1. помощники (сессия, сотрудник, клавиатуры, тексты);
2. `/start` — приветствие и поток первого запуска (подразделение → опыт);
3. главное меню;
4. чек-лист смены (отметка пункта, фотоотчёт);
5. поручения (принять / в работу / выполнено / фото / проблема);
6. полезные ссылки;
7. приём фото и текста (обработка «ожидающего действия»).

Всё это работает ТОЛЬКО в личке (`chat.type == "private"`): в групповом чате
остаются наследные механики, и мешать им HR-бот не должен. Обработчик текста
пропускает команды (`/...`) дальше — иначе он бы «съел» `/whoami` и `/help`.
"""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.hr_models import (
    EXPERIENCE_EXPERIENCED,
    EXPERIENCE_NEW,
    ONBOARDING_DONE,
    ROLE_ADMIN,
    ROLE_AUP,
    TASK_ACCEPTED,
    TASK_DONE,
    TASK_IN_PROGRESS,
    TASK_ON_REVIEW,
    TASK_SCOPE_DEPARTMENT,
    TEMPLATE_CLOSE,
    TEMPLATE_FIRST_DAY,
    ChecklistItem,
    Employee,
)
from app.db.models import User
from app.services import (
    hr_access,
    hr_checklists,
    hr_demo,
    hr_departments,
    hr_feed,
    hr_links,
    hr_media,
    hr_pending,
    hr_reminders,
    hr_reports,
    hr_reset,
    hr_settings,
    hr_tasks,
)

log = structlog.get_logger()
router = Router(name="hr")

# Префикс callback-данных HR-бота. Один на все кнопки — легко узнать «своё».
CB = "hr"

ROLE_LABEL = {
    "employee": "Сотрудник",
    ROLE_AUP: "Руководитель",
    ROLE_ADMIN: "Администратор",
}

GREETING = (
    "👋 <b>Привет! Это рабочий бот ресторана.</b>\n\n"
    "Здесь ты найдёшь чек-листы своей смены, поручения руководства, "
    "расписание встреч и полезные ссылки."
)


# ==========================================================================
# 1. Помощники
# ==========================================================================


async def _load(
    session: AsyncSession, telegram_id: int
) -> tuple[User, Employee] | None:
    """Пользователь + его HR-профиль (создаётся при первом заходе)."""
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        return None
    try:
        employee = await hr_access.ensure_employee(session, user)
    except hr_access.HrAccessError:
        # Уволенный сотрудник: бот тоже закрыт, пока не вернут из корзины.
        # Возвращаем `None` — вызывающие уже умеют объяснить, что доступа нет.
        log.info("hr.bot_access_denied", telegram_id=telegram_id)
        await session.rollback()
        return None
    await session.commit()
    return user, employee


async def _department_name(session: AsyncSession, department_id: int | None) -> str:
    if department_id is None:
        return "не выбрано"
    dept = await hr_departments.get_department(session, department_id)
    return dept.name if dept else "не выбрано"


def badge_text(employee: Employee) -> str:
    """Плашка должность/звание: « 🛠 <b>Разработчик</b>» или пустая строка.

    Плашку ставит только админ (или сид владельцев), поэтому здесь нет никакой
    логики прав — это чистая подпись рядом с именем.
    """
    if not employee.badge:
        return ""
    prefix = f"{employee.badge_emoji} " if employee.badge_emoji else ""
    return f"\n{prefix}<b>{employee.badge}</b>"


def demo_mark(employee: Employee) -> str:
    """Пометка тестового пула — рядом с именем, чтобы не спутать с боевыми."""
    return f" {hr_demo.DEMO_PREFIX}" if employee.is_demo else ""


def _app_url(suffix: str = "") -> str:
    base = get_settings().mini_app_url.rstrip("/")
    return f"{base}/{suffix.lstrip('/')}" if suffix else base


def _app_button(text: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=_app_url()))


def departments_kb(departments: list) -> InlineKeyboardMarkup:  # noqa: ANN001
    rows = [
        [
            InlineKeyboardButton(
                text=f"{d.emoji or '•'} {d.name}", callback_data=f"{CB}:dept:{d.id}"
            )
        ]
        for d in departments
    ]
    rows.append([_app_button("📱 Открыть приложение")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def experience_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌱 Я только начал(а) работать",
                    callback_data=f"{CB}:exp:{EXPERIENCE_NEW}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💼 Я работаю давно",
                    callback_data=f"{CB}:exp:{EXPERIENCE_EXPERIENCED}",
                )
            ],
        ]
    )


def main_menu_kb(employee: Employee) -> InlineKeyboardMarkup:
    """Главное меню (п.10 mainPROMT). Управляющим — дополнительный блок."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="📋 Чек-лист смены", callback_data=f"{CB}:chk"),
            InlineKeyboardButton(text="✅ Мои задачи", callback_data=f"{CB}:tasks"),
        ],
        [
            InlineKeyboardButton(text="🔗 Полезные ссылки", callback_data=f"{CB}:links"),
            InlineKeyboardButton(text="📝 Обратная связь", callback_data=f"{CB}:feedback"),
        ],
        [
            InlineKeyboardButton(text="👤 Мой профиль", callback_data=f"{CB}:profile"),
        ],
    ]
    if hr_access.is_aup(employee):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗂 Лента и отчёты", callback_data=f"{CB}:feed"
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔭 Эскалации: прогноз", callback_data=f"{CB}:escalations"
                )
            ]
        )
        # Опасная кнопка с двумя подтверждениями — ниже в обработчиках.
        rows.append(
            [
                InlineKeyboardButton(
                    text="🧹 Сброс текущей работы", callback_data=f"{CB}:reset"
                )
            ]
        )
    if hr_access.is_admin(employee):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🧪 Тестовый пул [BOT]", callback_data=f"{CB}:demo"
                )
            ]
        )
    rows.append([_app_button("📱 Открыть приложение")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_text(name: str, department: str, employee: Employee) -> str:
    return (
        f"👤 <b>{name}</b>{demo_mark(employee)} — "
        f"{ROLE_LABEL.get(employee.role, employee.role)}"
        f"{badge_text(employee)}\n"
        f"Подразделение: {department}\n\n"
        "Выбери раздел:"
    )


async def _answer(
    callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    """Отредактировать сообщение под кнопкой (без спама новыми сообщениями)."""
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(  # type: ignore[union-attr]
            text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True
        )
    except TelegramBadRequest:
        # «message is not modified» — обычное дело при повторном тапе: молчим.
        pass


# ==========================================================================
# 2. Старт и онбординг
# ==========================================================================


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    if message.from_user is None or message.chat.type != "private":
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, message.from_user.id)
        if ctx is None:
            # Пользователя нет в базе: в новом продукте сотрудник заводится
            # администратором, поэтому честно просим ID для добавления.
            await message.answer(
                "🛑 Тебя пока нет в списке сотрудников.\n"
                "Нажми /whoami и передай свой ID администратору.",
                parse_mode="HTML",
            )
            return
        _user, employee = ctx
        departments = await hr_departments.list_departments(session)

    if employee.onboarding_state != ONBOARDING_DONE:
        if not departments:
            await message.answer(
                "Пока не настроено ни одного подразделения — "
                "попроси администратора добавить их в приложении."
            )
            return
        await message.answer(
            GREETING + "\n\n<b>Шаг 1 из 2.</b> Выбери своё подразделение:",
            parse_mode="HTML",
            reply_markup=departments_kb(departments),
        )
        return

    await _show_menu(message, employee)


@router.message(Command("menu"))
async def on_menu(message: Message) -> None:
    if message.from_user is None or message.chat.type != "private":
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, message.from_user.id)
        if ctx is None:
            return
        _user, employee = ctx
    await _show_menu(message, employee)


async def _show_menu(message: Message, employee: Employee) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        user = await session.get(User, employee.user_id)
        department = await _department_name(session, employee.department_id)
    name = user.display_name if user else "Сотрудник"
    await message.answer(
        menu_text(name, department, employee),
        parse_mode="HTML",
        reply_markup=main_menu_kb(employee),
    )


@router.callback_query(F.data.startswith(f"{CB}:dept:"))
async def on_pick_department(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        return
    department_id = int(callback.data.rsplit(":", 1)[1])
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        dept = await hr_departments.get_department(session, department_id)
        if dept is None or not dept.is_active:
            await callback.answer("Подразделение недоступно", show_alert=True)
            return
        employee.department_id = dept.id
        if employee.experience is None:
            employee.onboarding_state = "experience"
        else:
            employee.onboarding_state = ONBOARDING_DONE
        await session.commit()
        dept_name = dept.name
    await callback.answer()
    await _answer(
        callback,
        f"Подразделение: <b>{dept_name}</b>\n\n"
        "<b>Шаг 2 из 2.</b> Как давно ты работаешь?",
        experience_kb(),
    )


@router.callback_query(F.data.startswith(f"{CB}:exp:"))
async def on_pick_experience(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        return
    experience = callback.data.rsplit(":", 1)[1]
    if experience not in {EXPERIENCE_NEW, EXPERIENCE_EXPERIENCED}:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        employee.experience = experience
        employee.onboarding_state = ONBOARDING_DONE
        await session.commit()
        department = await _department_name(session, employee.department_id)
        user = await session.get(User, employee.user_id)
    await callback.answer("Готово!")
    await _answer(
        callback,
        "Отлично, настройка завершена.\n\n"
        + menu_text(user.display_name if user else "Сотрудник", department, employee),
        main_menu_kb(employee),
    )


@router.callback_query(F.data == f"{CB}:menu")
async def on_menu_cb(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        department = await _department_name(session, employee.department_id)
        user = await session.get(User, employee.user_id)
    await callback.answer()
    await _answer(
        callback,
        menu_text(user.display_name if user else "Сотрудник", department, employee),
        main_menu_kb(employee),
    )


@router.callback_query(F.data == f"{CB}:profile")
async def on_profile(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        user, employee = ctx
        department = await _department_name(session, employee.department_id)
        open_tasks = await hr_tasks.list_for_employee(session, employee)
    await callback.answer()
    await _answer(
        callback,
        f"👤 <b>{user.display_name}</b>{demo_mark(employee)}{badge_text(employee)}\n"
        f"Должность: {employee.position or '—'}\n"
        f"Роль: {ROLE_LABEL.get(employee.role, employee.role)}\n"
        f"Подразделение: {department}\n"
        f"Опыт: {'только начал(а)' if employee.experience == EXPERIENCE_NEW else 'опытный'}\n"
        f"Открытых поручений: {len(open_tasks)}",
        _back_kb(),
    )


def _demo_kb(visible: bool, count: int) -> InlineKeyboardMarkup:
    """Один экран на все действия с тестовым пулом: завести → показать/спрятать
    → симулировать → снести следы. Удаление — отдельные кнопки, потому что
    тумблер видимости обратим, а удаление нет."""
    toggle = "🙈 Скрыть следы" if visible else "👁 Показать следы"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🆕 Завести пул ({count})", callback_data=f"{CB}:demo:seed"
                ),
                InlineKeyboardButton(text=toggle, callback_data=f"{CB}:demo:vis"),
            ],
            [
                InlineKeyboardButton(
                    text="▶️ Симулировать смены", callback_data=f"{CB}:demo:sim"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧹 Снести только активность",
                    callback_data=f"{CB}:demo:purge",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить сотрудников и следы",
                    callback_data=f"{CB}:demo:purgeall",
                )
            ],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")],
        ]
    )


def _demo_text(data: hr_demo.DemoOverview) -> str:
    lines = [
        "🧪 <b>Тестовый пул активности</b>",
        f"Префикс: <code>{data.prefix}</code>",
        f"Следы сейчас: {'👁 видны' if data.visible else '🙈 скрыты'}",
        "",
    ]
    if not data.employees:
        lines.append("Пул не заведён — нажми «Завести пул».")
    else:
        for row in data.employees:
            badge = f" · {row.badge}" if row.badge else ""
            lines.append(
                f"• {row.display_name} — "
                f"{row.department_name or 'без подразделения'}{badge}"
            )
        lines.append("")
        lines.append(
            "Активность: смен "
            f"{data.activity.checklist_runs}, поручений "
            f"{data.activity.tasks}, ответов ОС "
            f"{data.activity.feedback_answers}"
        )
    lines.append("")
    lines.append("Тумблер прячет пул из ленты, списков и отчётов, не удаляя данные.")
    return "\n".join(lines)


async def _render_demo(callback: CallbackQuery) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        data = await hr_demo.overview(session)
    await _answer(
        callback,
        _demo_text(data),
        _demo_kb(data.visible, len(data.employees)),
    )


@router.callback_query(F.data == f"{CB}:demo")
async def on_demo(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None or not hr_access.is_admin(ctx[1]):
            await callback.answer("Только для админа", show_alert=True)
            return
    await callback.answer()
    await _render_demo(callback)


@router.callback_query(F.data == f"{CB}:demo:seed")
async def on_demo_seed(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None or not hr_access.is_admin(ctx[1]):
            await callback.answer("Только для админа", show_alert=True)
            return
        created = await hr_demo.seed_pool(session)
        await session.commit()
    await callback.answer(f"Завели: {created}", show_alert=False)
    await _render_demo(callback)


@router.callback_query(F.data == f"{CB}:demo:vis")
async def on_demo_visibility(callback: CallbackQuery) -> None:
    """Тот самый один переключатель: спрятать или показать следы пула."""
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None or not hr_access.is_admin(ctx[1]):
            await callback.answer("Только для админа", show_alert=True)
            return
        visible = await hr_settings.get_demo_visible(session)
        await hr_settings.set_demo_visible(session, not visible)
    await callback.answer("Скрыли" if visible else "Показали")
    await _render_demo(callback)


@router.callback_query(F.data == f"{CB}:demo:sim")
async def on_demo_simulate(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None or not hr_access.is_admin(ctx[1]):
            await callback.answer("Только для админа", show_alert=True)
            return
        counters = await hr_demo.simulate(session, days=3)
    await callback.answer(
        f"Смен: {counters.get('checklist_runs', 0)}, поручений: {counters.get('tasks', 0)}"
    )
    await _render_demo(callback)


@router.callback_query(F.data.in_({f"{CB}:demo:purge", f"{CB}:demo:purgeall"}))
async def on_demo_purge(callback: CallbackQuery) -> None:
    """Снести следы пула: только активность или ещё и самих сотрудников."""
    if callback.from_user is None or callback.data is None:
        return
    delete_employees = callback.data.endswith("purgeall")
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None or not hr_access.is_admin(ctx[1]):
            await callback.answer("Только для админа", show_alert=True)
            return
        counters = await hr_demo.purge(session, delete_employees=delete_employees)
    removed = counters.get("tasks", 0) + counters.get("checklist_runs", 0)
    await callback.answer(f"Снесли записей: {removed}")
    await _render_demo(callback)


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")]
        ]
    )


# ==========================================================================
# 3. Чек-лист смены
# ==========================================================================


def _checklist_kb(view: hr_checklists.ChecklistView) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in view.items:
        if item.done:
            mark = "✅"
            data = f"{CB}:noop"
        elif item.requires_photo:
            mark = "📷"
            data = f"{CB}:chkp:{item.id}"
        else:
            mark = "⬜️"
            data = f"{CB}:chk:{item.id}"
        rows.append([InlineKeyboardButton(text=f"{mark} {item.title}", callback_data=data)])
    rows.append(
        [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _checklist_text(view: hr_checklists.ChecklistView) -> str:
    if view.needs_hall:
        return (
            "📋 <b>Чек-лист смены</b>\n\n"
            "Сначала выбери зал, в котором сегодня работаешь: "
            "у каждого зала свой чек-лист открытия."
        )
    if view.template_id is None:
        return (
            "📋 <b>Чек-лист смены</b>\n\n"
            "Для твоего подразделения чек-лист ещё не заведён. "
            "Обратись к администратору."
        )
    if view.kind == TEMPLATE_FIRST_DAY:
        kind_label = "Первый рабочий день"
    elif view.kind == TEMPLATE_CLOSE:
        kind_label = "Закрытие смены"
    else:
        kind_label = "Смена"
    hall_label = f" · {view.hall_name}" if view.hall_name else ""
    return (
        f"📋 <b>{view.template_title}</b>\n"
        f"{kind_label}{hall_label} · {view.shift_date.strftime('%d.%m.%Y')}\n\n"
        f"Выполнено {view.progress.done} из {view.progress.total}\n"
        "⬜️ — отметить, 📷 — нужен фотоотчёт, ✅ — готово"
    )


async def _render_checklist(callback: CallbackQuery, employee: Employee) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        view = await hr_checklists.build_view(session, employee)
        halls = await hr_checklists.list_halls(session) if view.needs_hall else []
    if view.needs_hall:
        rows = [
            [
                InlineKeyboardButton(
                    text=f"🚪 {hall.name}",
                    callback_data=f"{CB}:chkh:{hall.id}",
                )
            ]
            for hall in halls
        ]
        rows.append(
            [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")]
        )
        await _answer(
            callback, _checklist_text(view), InlineKeyboardMarkup(inline_keyboard=rows)
        )
        return
    await _answer(callback, _checklist_text(view), _checklist_kb(view))


@router.callback_query(F.data.startswith(f"{CB}:chkh:"))
async def on_checklist_hall(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        return
    hall_id = int(callback.data.rsplit(":", 1)[1])
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        hall = await hr_checklists.get_hall(session, hall_id)
        if hall is None or not hall.is_active:
            await callback.answer("Зал не найден", show_alert=True)
            return
        hall_name = hall.name
        await hr_checklists.choose_hall(
            session,
            employee=employee,
            hall=hall,
            shift_date=hr_checklists.local_today(),
        )
        await session.commit()
    await callback.answer(f"Зал: {hall_name}")
    await _render_checklist(callback, employee)


@router.callback_query(F.data == f"{CB}:chk")
async def on_checklist(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
    await callback.answer()
    await _render_checklist(callback, employee)


@router.callback_query(F.data.startswith(f"{CB}:chk:"))
async def on_checklist_done(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        return
    item_id = int(callback.data.rsplit(":", 1)[1])
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        item = await session.get(ChecklistItem, item_id)
        if item is None:
            await callback.answer("Пункт не найден", show_alert=True)
            return
        template = await hr_checklists.get_template(session, item.template_id)
        if template is None:
            await callback.answer("Шаблон не найден", show_alert=True)
            return
        run = await hr_checklists.get_or_create_run(
            session, employee, template, hr_checklists.local_today()
        )
        try:
            await hr_checklists.complete_item(
                session, employee=employee, run=run, item=item
            )
        except hr_checklists.ChecklistError as exc:
            await callback.answer(f"Не получилось: {exc}", show_alert=True)
            return
        await session.commit()
        view = await hr_checklists.build_view(session, employee, kind=template.kind)
    await callback.answer("Отмечено")
    if view.progress.finished:
        await _answer(
            callback,
            _checklist_text(view) + "\n\n✅ Чек-лист закрыт полностью — красота!",
            _checklist_kb(view),
        )
    else:
        await _answer(callback, _checklist_text(view), _checklist_kb(view))


@router.callback_query(F.data.startswith(f"{CB}:chkp:"))
async def on_checklist_photo_request(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        return
    item_id = int(callback.data.rsplit(":", 1)[1])
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        await hr_pending.set_pending(
            session,
            callback.from_user.id,
            hr_pending.Pending(
                kind=hr_pending.KIND_CHECKLIST_PHOTO,
                target_id=item_id,
                extra={"employee_id": employee.id},
            ),
        )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(  # type: ignore[union-attr]
            "📷 Пришли фото отчётом — засчитаю этот пункт чек-листа.",
            parse_mode="HTML",
        )


# ==========================================================================
# 4. Поручения
# ==========================================================================


def _tasks_kb(tasks: list) -> InlineKeyboardMarkup:  # noqa: ANN001
    rows = [
        [
            InlineKeyboardButton(
                text=f"{_status_emoji(t.status)} {t.title[:40]}", callback_data=f"{CB}:task:{t.id}"
            )
        ]
        for t in tasks[:10]
    ]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _status_emoji(status: str) -> str:
    return {
        "new": "🆕",
        "accepted": "👌",
        "in_progress": "🔄",
        # Сдано руководителю / возвращено на доработку (MEGAPROMT2).
        "on_review": "🔍",
        "rework": "↩️",
        "done": "✅",
        "overdue": "⏰",
        "failed": "⚠️",
    }.get(status, "•")


def _task_text(task, issues: list, photos: list) -> str:  # noqa: ANN001
    lines = [f"{_status_emoji(task.status)} <b>{task.title}</b>"]
    if task.description:
        lines.append(task.description)
    if task.expected_result:
        lines.append(f"Ожидаемый результат: {task.expected_result}")
    if task.due_at is not None:
        overdue = " ⏰ просрочено" if hr_tasks.is_overdue(task) else ""
        lines.append(f"Срок: {task.due_at.strftime('%d.%m %H:%M')}{overdue}")
    if task.requires_photo:
        lines.append("📷 Нужен фотоотчёт")
    if task.comment:
        lines.append(f"💬 {task.comment}")
    if photos:
        lines.append(f"📸 Фотоотчётов: {len(photos)}")
    if issues:
        last = issues[0]
        reason = f" ({last.reason_code})" if last.reason_code else ""
        lines.append(f"⚠️ Проблема{reason}: {last.comment or 'без комментария'}")
    audience = (
        "подразделение" if task.scope == TASK_SCOPE_DEPARTMENT else "лично"
    )
    lines.append(f"Получатель: {audience}")
    return "\n".join(lines)


def _task_kb(task) -> InlineKeyboardMarkup:  # noqa: ANN001
    rows: list[list[InlineKeyboardButton]] = []
    if task.status == "new":
        rows.append(
            [
                InlineKeyboardButton(
                    text="👌 Принять", callback_data=f"{CB}:tst:{task.id}:{TASK_ACCEPTED}"
                )
            ]
        )
    if task.status in {"new", "accepted", "overdue"}:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔄 В работу",
                    callback_data=f"{CB}:tst:{task.id}:{TASK_IN_PROGRESS}",
                )
            ]
        )
    if task.requires_photo:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📷 Отправить фотоотчёт", callback_data=f"{CB}:tph:{task.id}"
                )
            ]
        )
    if not task.requires_photo and task.status != TASK_DONE:
        # С проверкой работа не закрывается кнопкой: она уходит руководителю
        # (`on_review`) и ждёт приёмки. Без проверки — прежнее поведение.
        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        "📤 Сдать на проверку"
                        if task.requires_review
                        else "✅ Отметить выполненной"
                    ),
                    callback_data=(
                        f"{CB}:tst:{task.id}:{TASK_ON_REVIEW}"
                        if task.requires_review
                        else f"{CB}:tst:{task.id}:{TASK_DONE}"
                    ),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⚠️ Не успеваю / проблема", callback_data=f"{CB}:tis:{task.id}"
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="⬅️ К задачам", callback_data=f"{CB}:tasks")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == f"{CB}:tasks")
async def on_tasks(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        tasks = await hr_tasks.list_for_employee(session, employee)
    await callback.answer()
    if not tasks:
        await _answer(
            callback,
            "✅ <b>Открытых поручений нет.</b>\n\nКак появится — придёт уведомление.",
            _back_kb(),
        )
        return
    overdue = sum(1 for t in tasks if hr_tasks.is_overdue(t))
    text = f"✅ <b>Мои задачи</b> ({len(tasks)})\n"
    if overdue:
        text += f"⏰ просрочено: {overdue}\n"
    text += "\nВыбери поручение:"
    await _answer(callback, text, _tasks_kb(tasks))


async def _render_task(callback: CallbackQuery, employee: Employee, task_id: int) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        task = await hr_tasks.get_task(session, task_id)
        if task is None:
            await callback.answer("Поручение не найдено", show_alert=True)
            return
        issues = await hr_tasks.issues_of(session, task_id)
        photos = await hr_tasks.photos_of(session, task_id)
    text = _task_text(task, issues, photos)
    await _answer(callback, text, _task_kb(task))


@router.callback_query(F.data.startswith(f"{CB}:task:"))
async def on_task_detail(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        return
    task_id = int(callback.data.rsplit(":", 1)[1])
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
    await callback.answer()
    await _render_task(callback, employee, task_id)


@router.callback_query(F.data.startswith(f"{CB}:tst:"))
async def on_task_status(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        return
    _, _, raw_id, to_status = callback.data.split(":", 3)
    task_id = int(raw_id)
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        task = await hr_tasks.get_task(session, task_id)
        if task is None:
            await callback.answer("Поручение не найдено", show_alert=True)
            return
        if to_status in {TASK_DONE, TASK_ON_REVIEW} and task.requires_photo:
            photos = await hr_tasks.photos_of(session, task_id)
            if not photos:
                await callback.answer(
                    "Сначала пришли фотоотчёт", show_alert=True
                )
                return
        try:
            if to_status in {TASK_DONE, TASK_ON_REVIEW} and task.requires_review:
                # Старые кнопки в истории чата вели в `done` — на поручении с
                # проверкой это теперь сдача, а не закрытие.
                await hr_tasks.submit_work(session, task, employee)
            else:
                await hr_tasks.change_status(
                    session, task, to_status, by=employee
                )
        except hr_tasks.TaskError as exc:
            await callback.answer(f"Так нельзя: {exc}", show_alert=True)
            return
        await session.commit()
    await callback.answer("Записал")
    await _render_task(callback, employee, task_id)


@router.callback_query(F.data.startswith(f"{CB}:tph:"))
async def on_task_photo_request(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        return
    task_id = int(callback.data.rsplit(":", 1)[1])
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        await hr_pending.set_pending(
            session,
            callback.from_user.id,
            hr_pending.Pending(
                kind=hr_pending.KIND_TASK_PHOTO,
                target_id=task_id,
                extra={"employee_id": employee.id},
            ),
        )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(  # type: ignore[union-attr]
            "📷 Жду фотоотчёт — как получу, поручение закроется автоматически.",
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith(f"{CB}:tis:"))
async def on_task_issue_request(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.data is None:
        return
    task_id = int(callback.data.rsplit(":", 1)[1])
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        await hr_pending.set_pending(
            session,
            callback.from_user.id,
            hr_pending.Pending(
                kind=hr_pending.KIND_TASK_ISSUE,
                target_id=task_id,
                extra={"employee_id": employee.id},
            ),
        )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(  # type: ignore[union-attr]
            "⚠️ Опиши одним сообщением, что мешает и почему не успеваешь.\n"
            "Руководитель получит это вместе с уведомлением.",
            parse_mode="HTML",
        )


# ==========================================================================
# 5. Полезные ссылки
# ==========================================================================


@router.message(F.chat.type == "private", Command("report"))
async def on_report(message: Message) -> None:
    """`/report` — короткая сводка смены для руководителя.

    Сотруднику команда не нужна и в каталоге она видна всем, поэтому вместо
    «нет доступа» объясняем, у кого отчёт есть.
    """
    if message.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, message.from_user.id)
        if ctx is None:
            await message.answer("Сначала открой меню: /start")
            return
        _user, employee = ctx
        if not hr_access.is_aup(employee):
            await message.answer("📊 Отчёт смены доступен руководителю.")
            return
        report = await hr_reports.build_shift_report(session, viewer=employee)
    await message.answer(
        hr_reports.format_telegram(report),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [_app_button("📊 Отчёт в приложении")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")],
            ]
        ),
    )


@router.callback_query(F.data == f"{CB}:escalations")
async def on_escalations(callback: CallbackQuery) -> None:
    """Сухой прогон второй ступени прямо в чате. Ничего не отправляет."""
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        if not hr_access.is_aup(employee):
            await callback.answer("Недоступно", show_alert=True)
            return
        plan = await hr_reminders.escalation_plan(session)
    await callback.answer()
    await _answer(
        callback,
        hr_reminders.format_plan(plan),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")],
            ]
        ),
    )


@router.message(F.chat.type == "private", Command("escalations"))
async def on_escalations_cmd(message: Message) -> None:
    """`/escalations` — тот же прогноз без меню (для админов)."""
    if message.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, message.from_user.id)
        if ctx is None:
            await message.answer("Сначала открой меню: /start")
            return
        _user, employee = ctx
        if not hr_access.is_admin(employee):
            await message.answer("🔭 Прогноз эскалаций доступен администратору.")
            return
        plan = await hr_reminders.escalation_plan(session)
    await message.answer(
        hr_reminders.format_plan(plan),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")],
            ]
        ),
    )


@router.callback_query(F.data == f"{CB}:reset")
async def on_reset_preview(callback: CallbackQuery) -> None:
    """Первое подтверждение: показываем сухой счёт и кнопку «Подтвердить»."""
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        if not hr_access.is_aup(employee):
            await callback.answer("Недоступно", show_alert=True)
            return
        view = await hr_reset.preview(session, employee)
    await callback.answer()
    if view.counts.tasks == 0 and view.counts.issues == 0:
        await _answer(
            callback,
            hr_reset.preview_text(view),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")],
                ]
            ),
        )
        return
    await _answer(
        callback,
        hr_reset.preview_text(view),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Подтвердить сброс", callback_data=f"{CB}:reset:do"
                    )
                ],
                [InlineKeyboardButton(text="Отмена", callback_data=f"{CB}:menu")],
            ]
        ),
    )


@router.callback_query(F.data == f"{CB}:reset:do")
async def on_reset_execute(callback: CallbackQuery) -> None:
    """Второе подтверждение: тот же человек нажал ещё раз — удаляем."""
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        if not hr_access.is_aup(employee):
            await callback.answer("Недоступно", show_alert=True)
            return
        view = await hr_reset.preview(session, employee)
        try:
            counts = await hr_reset.execute(
                session,
                employee,
                token=view.token,
                confirm=hr_reset.CONFIRM_WORD,
            )
        except hr_access.HrAccessError:
            await callback.answer("Данные изменились — попробуй ещё раз", show_alert=True)
            return
    await callback.answer()
    await _answer(
        callback,
        (
            "🧹 <b>Готово</b>\n\n"
            f"Удалено поручений: <b>{counts.tasks}</b>\n"
            f"Удалено проблем: <b>{counts.issues}</b>\n"
            f"Уведомлений по ним: {counts.notifications}"
        ),
        _back_kb(),
    )


@router.callback_query(F.data == f"{CB}:links")
async def on_links(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        links = await hr_links.list_links(session, employee)
    await callback.answer()
    if not links:
        await _answer(
            callback, "🔗 Полезных ссылок пока нет.", _back_kb()
        )
        return
    rows = [
        [
            InlineKeyboardButton(
                text=f"{link.emoji or '🔗'} {link.title}", url=link.url
            )
        ]
        for link in links
    ]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")])
    await _answer(
        callback,
        "🔗 <b>Полезные ссылки</b>\n\nГрафик, фудбук и всё, что добавила администрация.",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == f"{CB}:feedback")
async def on_feedback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _answer(
        callback,
        "📝 <b>Обратная связь по смене</b>\n\n"
        "Короткая форма открывается в приложении — так удобнее отвечать по шкале.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [_app_button("📝 Заполнить форму")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")],
            ]
        ),
    )


@router.callback_query(F.data == f"{CB}:feed")
async def on_feed_hint(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            await callback.answer("Нет доступа", show_alert=True)
            return
        _user, employee = ctx
        if not hr_access.is_aup(employee):
            await callback.answer("Недоступно", show_alert=True)
            return
        items = await hr_feed.build_feed(session, employee, limit=10)
        scope = hr_feed.viewer_scope(employee)
    await callback.answer()
    if not items:
        await _answer(callback, "🗂 Пока нет событий.", _back_kb())
        return
    lines = ["🗂 <b>Последние события</b>", ""]
    for item in items:
        stamp = item.at.strftime("%d.%m %H:%M") if item.at else "—"
        lines.append(f"{stamp} · {item.display_name}: {item.text}")
    scope_hint = {
        hr_feed.SCOPE_ALL: "Видно всё — фильтры по сотрудникам и подразделениям в приложении.",
        hr_feed.SCOPE_DEPARTMENT: "Видно своё подразделение.",
    }.get(scope, "")
    if scope_hint:
        lines.append("")
        lines.append(scope_hint)
    lines.append("\nПолная лента с фильтрами — в приложении.")
    await _answer(
        callback,
        "\n".join(lines),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [_app_button("🗂 Открыть ленту")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data=f"{CB}:menu")],
            ]
        ),
    )


@router.callback_query(F.data == f"{CB}:noop")
async def on_noop(callback: CallbackQuery) -> None:
    await callback.answer("Уже отмечено ✅")


# ==========================================================================
# 6. Приём фото и текста (обработка ожидающего действия)
# ==========================================================================


@router.message(F.chat.type == "private", F.photo)
async def on_photo(message: Message) -> None:
    """Фото в личке: закрываем ожидание — пункт чек-листа или фотоотчёт."""
    if message.from_user is None or not message.photo:
        return
    # Самый крупный размер — полноценный снимок, а не превью.
    await _accept_private_media(message, message.photo[-1].file_id)


@router.message(F.chat.type == "private", F.document)
async def on_photo_document(message: Message) -> None:
    """Снимок, отправленный файлом («без сжатия»), тоже считается фотоотчётом.

    iPhone и Android умеют присылать фото как документ (`image/heic`, `image/jpeg`).
    Раньше такой апдейт не матчился ни одним хендлером: бот молчал, и выглядело
    это как «фото вообще не работают». Теперь это тот же путь, что и F.photo.
    """
    document = message.document
    if message.from_user is None or document is None:
        return
    mime = (document.mime_type or "").lower()
    if not mime.startswith("image/"):
        raise SkipHandler()
    await _accept_private_media(message, document.file_id)


async def _accept_private_media(message: Message, file_id: str) -> None:
    """Общий приём снимка: pending (чек-лист/поручение) → запись + кеш байтов."""
    if message.from_user is None:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        pending = await hr_pending.get_pending(session, message.from_user.id)
        if pending is None:
            # Нет ожидания — фото не наше: отдаём дальше по цепочке роутеров
            # (в личке наследные механики могут хотеть своё).
            raise SkipHandler()
        ctx = await _load(session, message.from_user.id)
        if ctx is None:
            return
        _user, employee = ctx

        if pending.kind == hr_pending.KIND_TASK_PHOTO:
            task = await hr_tasks.get_task(session, pending.target_id)
            if task is None:
                await hr_pending.clear_pending(session, message.from_user.id)
                await message.answer("Поручение не найдено.")
                return
            photo = await hr_tasks.add_photo(
                session, task, employee=employee, file_id=file_id
            )
            # Кешируем байты, чтобы фото открывалось в приложении, даже когда
            # Telegram недоступен. Сбой сети не мешает приёму отчёта.
            blob = await hr_media.cache_telegram_photo(session, file_id)
            if blob is not None:
                photo.media_id = blob.id
            await session.commit()
            await hr_pending.clear_pending(session, message.from_user.id)
            done = task.status == TASK_DONE
            await message.answer(
                "✅ Фотоотчёт принят."
                + (" Поручение закрыто." if done else " Руководитель увидит его в задаче."),
                parse_mode="HTML",
            )
            return

        if pending.kind == hr_pending.KIND_CHECKLIST_PHOTO:
            item = await session.get(ChecklistItem, pending.target_id)
            if item is None:
                await hr_pending.clear_pending(session, message.from_user.id)
                await message.answer("Пункт не найден.")
                return
            template = await hr_checklists.get_template(session, item.template_id)
            if template is None:
                await hr_pending.clear_pending(session, message.from_user.id)
                return
            run = await hr_checklists.get_or_create_run(
                session, employee, template, hr_checklists.local_today()
            )
            # Кешируем снимок в блоб: пункт остаётся видимым в приложении и
            # без доступа к Bot API (см. `services/hr_media`).
            blob = await hr_media.cache_telegram_photo(session, file_id)
            await hr_checklists.complete_item(
                session,
                employee=employee,
                run=run,
                item=item,
                photo_file_id=file_id,
                photo_media_id=blob.id if blob is not None else None,
            )
            await session.commit()
            await hr_pending.clear_pending(session, message.from_user.id)
            view = await hr_checklists.build_view(session, employee, kind=template.kind)
            await message.answer(
                f"✅ Фотоотчёт принят.\n{view.progress.text()}", parse_mode="HTML"
            )
            return

        # Ожидание другого типа (например, комментарий) — текст важнее фото.
        await message.answer(
            "Сначала ответь текстом на предыдущий запрос.", parse_mode="HTML"
        )


@router.message(F.chat.type == "private", F.text)
async def on_text(message: Message) -> None:
    """Текст в личке: либо комментарий к «не успеваю», либо подсказка.

    Команды (`/...`) НЕ перехватываем — они должны дойти до своих роутеров
    (`/whoami`, `/help`, `/menu`), иначе бот «съест» их и промолчит.
    """
    if message.from_user is None or not message.text:
        raise SkipHandler()
    # Команды (`/whoami`, `/help`, `/menu`) не перехватываем: только
    # `raise SkipHandler()` реально передаёт апдейт следующему роутеру —
    # обычный `return` в aiogram 3 считается «обработано» и глушит команду.
    if message.text.startswith("/"):
        raise SkipHandler()

    sm = get_sessionmaker()
    async with sm() as session:
        pending = await hr_pending.get_pending(session, message.from_user.id)
        if pending is None or pending.kind != hr_pending.KIND_TASK_ISSUE:
            # Свободный текст не в контексте HR — пусть смотрят другие.
            raise SkipHandler()
        ctx = await _load(session, message.from_user.id)
        if ctx is None:
            return
        _user, employee = ctx
        task = await hr_tasks.get_task(session, pending.target_id)
        if task is None:
            await hr_pending.clear_pending(session, message.from_user.id)
            await message.answer("Поручение не найдено.")
            return
        from app.services import hr_notify
        from app.services.hr_reminders import managers

        comment = message.text.strip()[:1000]
        issue = await hr_tasks.add_issue(
            session, task, employee=employee, reason_code=None, comment=comment
        )
        await hr_notify.notify_issue(session, task, issue, await managers(session))
        await session.commit()
        await hr_pending.clear_pending(session, message.from_user.id)
    await message.answer(
        "⚠️ Передал руководителю. Поручение осталось за тобой — "
        "как разберёшься, отметь выполнение.",
        parse_mode="HTML",
    )


# ==========================================================================
# 8. Устаревшие кнопки
# ==========================================================================

# Отдельный роутер, а не `router`: диспетчер подключает его ПОСЛЕДНИМ.
# Иначе ловушка «любое нажатие» съела бы кнопки других сценариев (`hra:` —
# алерты руководителя) — они включены в диспетчер позже hr-роутера.
stale_router = Router(name="stale-buttons")


@stale_router.callback_query()
async def on_stale_callback(callback: CallbackQuery) -> None:
    """Любая кнопка, для которой в текущем коде нет обработчика.

    Так выглядит **старое сообщение**. Telegram не переписывает уже
    отправленные сообщения: меню, отправленное прошлой сборкой, хранит
    `callback_data`, которых в сегодняшнем коде уже нет (переименовали префикс,
    провели пункт — кнопка осталась). Человек нажимает, Telegram честно
    присылает апдейт, вебхук отвечает `200`, aiogram пишет
    `Update ... is not handled` — и в чате тишина, будто бот умер.

    Что делаем: не гадаем, какой смысл был у старой кнопки (его больше нет),
    а показываем актуальное меню и говорим об этом одной строкой. Это ровно
    то, что человек сделал бы сам через `/start`, только без догадки, что
    команду нужно помнить.
    """
    if callback.from_user is None:
        return
    log.info(
        "hr.bot_stale_callback",
        telegram_id=callback.from_user.id,
        data=(callback.data or "")[:64],
    )
    sm = get_sessionmaker()
    async with sm() as session:
        ctx = await _load(session, callback.from_user.id)
        if ctx is None:
            # Нет сотрудника — меню ему всё равно нечего показать, а тишина
            # выглядела бы как поломка. Называем единственный рабочий вход.
            await callback.answer("Меню устарело — отправь /start", show_alert=True)
            return
        user, employee = ctx
        department = await _department_name(session, employee.department_id)
        fresh = await session.get(User, employee.user_id)
    await callback.answer()
    await _answer(
        callback,
        "Это сообщение из прошлой версии меню — вот актуальное.\n\n"
        + menu_text(fresh.display_name if fresh else user.display_name, department, employee),
        main_menu_kb(employee),
    )
