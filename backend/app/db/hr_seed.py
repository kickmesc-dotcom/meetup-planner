"""Сид начальных данных HR-ядра (идемпотентный, ничего не перезаписывает).

Наполняем ровно один раз и только то, что явно задано в брифе
[mainPROMT.MD]: четыре подразделения и их чек-листы смены (§3.1–3.4), раздел
«Полезные ссылки» (§8) и вопросы обратной связи (§7). Дальше всё это
редактирует администратор из бота/мини-аппа — сид лишь снимает «пустой экран»
у нового ресторана.

Правила безопасности: если хоть одна запись нужного типа уже есть — блок
пропускается. Значит, повторный запуск на боевой базе ничего не затрёт, даже
если админ всё переименовал.

Шаблоны `first_day` НЕ заводим: онбординг-логика чек-листов уже умеет
откатываться на обычную смену (`select_template`), а придумывать за ресторан
содержимое первого дня — неправильно. Админ добавит его при необходимости.
"""

from __future__ import annotations

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    ONBOARDING_DONE,
    QUESTION_CHOICE,
    QUESTION_SCALE,
    QUESTION_TEXT,
    ROLE_ADMIN,
    TEMPLATE_SHIFT,
    ChecklistItem,
    ChecklistTemplate,
    Department,
    Employee,
    FeedbackQuestion,
    UsefulLink,
)
from app.db.models import User
from app.db.seed import color_for_user

log = structlog.get_logger()

# Владельцы и кураторы проекта. Telegram-ID те же, что в
# `config.BUILTIN_ADMIN_TG_IDS` — оттуда берётся максимальный доступ; здесь то,
# как эти два человека ПОДПИСАНЫ (плашка) и что они уже прошли знакомство.
# (tg_id, отображаемое имя, эмодзи плашки, текст плашки)
OWNERS: tuple[tuple[int, str, str, str], ...] = (
    (306733739, "Разработчик", "🛠", "Разработчик"),
    (397594558, "Дмитрий", "🧭", "Управляющий"),
)

# slug → (имя, эмодзи)
_DEPARTMENTS: tuple[tuple[str, str, str], ...] = (
    ("cook", "Повар", "👨‍🍳"),
    ("waiter", "Официант", "🍽"),
    ("barman", "Бармен", "🍸"),
    ("manager", "Менеджер", "📋"),
)

# slug → список (title, requires_photo, condition_position)
_CHECKLIST_ITEMS: dict[str, tuple[tuple[str, bool, str | None], ...]] = {
    "cook": (
        ("Переодеться в рабочую форму", False, None),
        ("Открыть смену в iiko", False, None),
        ("Проверить, включена ли вытяжка", False, None),
        ("Проверить журнал передачи смены", False, None),
        ("Проверить маркировки и заготовки", True, None),
        # Бракераж — только у сотрудника с этой обязанностью (пример из брифа).
        ("Провести бракераж продукции", False, "су-шеф"),
    ),
    "waiter": (
        ("Переодеться в рабочую форму", False, None),
        ("Открыть смену в iiko", False, None),
        (
            "Подготовить зал к открытию: протереть столы, проверить чистоту и "
            "состояние межсменной подготовки, пополнить салфетки",
            True,
            None,
        ),
    ),
    "barman": (
        ("Переодеться в рабочую форму", False, None),
        ("Открыть смену в iiko", False, None),
        ("Проверить журнал передачи смены, если он ведётся", False, None),
        ("Заполнить раздачу льдом", False, None),
        ("Проверить заготовки и маркировки", True, None),
    ),
    "manager": (
        (
            "Выполнить «большую 8» согласно внутреннему регламенту ресторана",
            False,
            None,
        ),
        ("Выключить свет в предусмотренных регламентом зонах", False, None),
        ("Включить музыку", False, None),
        ("Включить кассу", False, None),
        ("Проверить стоп-лист доставки", False, None),
    ),
}

# (code, text, kind, options)
_FEEDBACK_QUESTIONS: tuple[tuple[str, str, str, list[str]], ...] = (
    ("shift_mood", "Как прошла смена?", QUESTION_SCALE, []),
    ("problems", "Были ли проблемы, мешавшие работе?", QUESTION_TEXT, []),
    (
        "resources",
        "Всё ли необходимое было для выполнения задач?",
        QUESTION_CHOICE,
        ["Да", "Частично", "Нет"],
    ),
    ("suggestions", "Есть ли предложения по улучшению работы?", QUESTION_TEXT, []),
    ("need_help", "Нужна ли помощь руководителя?", QUESTION_CHOICE, ["Да", "Нет"]),
)

# (title, url, emoji) — плейсхолдеры: админ заменит на боевые ссылки.
_LINKS: tuple[tuple[str, str, str], ...] = (
    ("График", "https://example.com/schedule", "🗓"),
    ("Фудбук", "https://example.com/foodbook", "📖"),
)


async def _count(session: AsyncSession, model) -> int:  # noqa: ANN001
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def seed_departments(session: AsyncSession) -> dict[str, Department]:
    """Создать подразделения и их чек-листы смены, если их ещё нет."""
    existing = {
        d.slug: d for d in await session.scalars(select(Department).order_by(Department.id))
    }
    if existing:
        return existing

    created: dict[str, Department] = {}
    for index, (slug, name, emoji) in enumerate(_DEPARTMENTS):
        dept = Department(name=name, slug=slug, emoji=emoji, sort_order=index)
        session.add(dept)
        created[slug] = dept
    await session.flush()

    for slug, dept in created.items():
        template = ChecklistTemplate(
            department_id=dept.id,
            title=f"Чек-лист смены — {dept.name}",
            kind=TEMPLATE_SHIFT,
            sort_order=0,
        )
        session.add(template)
        await session.flush()
        for order, (title, requires_photo, condition) in enumerate(
            _CHECKLIST_ITEMS.get(slug, ())
        ):
            session.add(
                ChecklistItem(
                    template_id=template.id,
                    title=title,
                    requires_photo=requires_photo,
                    is_mandatory=True,
                    condition_position=condition,
                    sort_order=order,
                )
            )
        await session.flush()
    log.info("hr.seed_departments", count=len(created))
    return created


async def seed_feedback_questions(session: AsyncSession) -> int:
    if await _count(session, FeedbackQuestion) > 0:
        return 0
    for order, (code, text, kind, options) in enumerate(_FEEDBACK_QUESTIONS):
        session.add(
            FeedbackQuestion(
                code=code,
                text=text,
                kind=kind,
                options=list(options),
                sort_order=order,
            )
        )
    await session.flush()
    log.info("hr.seed_feedback_questions", count=len(_FEEDBACK_QUESTIONS))
    return len(_FEEDBACK_QUESTIONS)


async def seed_links(session: AsyncSession) -> int:
    if await _count(session, UsefulLink) > 0:
        return 0
    for order, (title, url, emoji) in enumerate(_LINKS):
        session.add(
            UsefulLink(title=title, url=url, emoji=emoji, sort_order=order)
        )
    await session.flush()
    log.info("hr.seed_links", count=len(_LINKS))
    return len(_LINKS)


async def seed_owners(session: AsyncSession) -> int:
    """Завести/дополнить профили владельцев проекта (плашка + роль `admin`).

    Идемпотентно и БЕЗ перезаписи того, что человек настроил сам: имя в `users`
    не трогаем (его может править бот), а у HR-профиля дописываем только плашку,
    роль и «знакомство пройдено». Без этого владелец попадал бы в поток
    первого запуска с вопросом «какое у тебя подразделение».
    """
    for tg_id, name, emoji, badge in OWNERS:
        user = await session.scalar(select(User).where(User.telegram_id == tg_id))
        if user is None:
            # Владельца может не быть в whitelist из env — тогда заводим его
            # здесь: без строки в `users` HR-профиль создать не на что.
            user = User(
                telegram_id=tg_id,
                display_name=name,
                color_hex=color_for_user(tg_id),
            )
            session.add(user)
            await session.flush()
            log.info("hr.seed_owner_user", telegram_id=tg_id)

        employee = await session.scalar(
            select(Employee).where(Employee.user_id == user.id)
        )
        if employee is None:
            session.add(
                Employee(
                    user_id=user.id,
                    role=ROLE_ADMIN,
                    badge=badge,
                    badge_emoji=emoji,
                    onboarding_state=ONBOARDING_DONE,
                )
            )
            log.info("hr.seed_owner_employee", telegram_id=tg_id, badge=badge)
            continue

        employee.role = ROLE_ADMIN
        employee.badge = badge
        employee.badge_emoji = emoji
        employee.onboarding_state = ONBOARDING_DONE
        employee.is_active = True
    await session.flush()
    return len(OWNERS)


async def seed_hr(session: AsyncSession) -> None:
    """Один вход для lifespan: владельцы → подразделения → вопросы → ссылки."""
    await seed_owners(session)
    await seed_departments(session)
    await seed_feedback_questions(session)
    await seed_links(session)
    await session.commit()
