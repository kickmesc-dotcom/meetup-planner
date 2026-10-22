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
    DEFAULT_PASS_PERCENT,
    ONBOARDING_DONE,
    QUESTION_CHOICE,
    QUESTION_SCALE,
    QUESTION_TEXT,
    ROLE_ADMIN,
    STANDARD_CATEGORY_DISHES,
    STANDARD_CATEGORY_EQUIPMENT,
    STANDARD_CATEGORY_SAFETY,
    STANDARD_CATEGORY_SERVICE,
    TEMPLATE_CLOSE,
    TEMPLATE_SHIFT,
    ChecklistItem,
    ChecklistTemplate,
    Department,
    Employee,
    FeedbackQuestion,
    Hall,
    Standard,
    StandardQuestion,
    UsefulLink,
)
from app.db.models import User
from app.db.seed import color_for_user
from app.services import display_names

log = structlog.get_logger()

# Владельцы и кураторы проекта. Telegram-ID те же, что в
# `config.BUILTIN_ADMIN_TG_IDS` — оттуда берётся максимальный доступ; здесь то,
# как эти два человека ПОДПИСАНЫ (плашка) и что они уже прошли знакомство.
# (tg_id, отображаемое имя, эмодзи плашки, текст плашки)
OWNERS: tuple[tuple[int, str, str, str], ...] = (
    # Раунд 5: «Серж-NEO» → «Сергей». Ник — не имя: в профиле и ленте он
    # читался как логин и обрезался до «Серж-…» на узком экране.
    (306733739, "Сергей", "🛠", "Разработчик"),
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


# --------------------------------------------------------------------------
# Залы и чек-листы открытия/закрытия (DOCX владельца)
# --------------------------------------------------------------------------

# (slug, name, sort_order)
_HALLS: tuple[tuple[str, str, int], ...] = (
    ("first", "Первый зал", 10),
    ("second", "Второй зал", 20),
)

# Открытие зала. Содержимое перенесено из «Чек-лист открытия и закрытия.docx»:
# ничего не придумано, только разбито на пункты. `True` — пункт требует фото.
_HALL_OPENING: dict[str, tuple[tuple[str, bool], ...]] = {
    "first": (
        (
            "Залить воду в отпариватель (стоит на 305 столе) и только после "
            "включить его, подождать пока нагреется",
            False,
        ),
        ("Поднять жалюзи (в летний сезон открываем окна)", False),
        (
            "Протереть столы 400–500 спецраствором: «Ника Экстра М» "
            "(стоит на полу с внутренней стороны мойки) + вода 1:2",
            False,
        ),
        (
            "Отпарить отпаривателем столы 100–300, зону раздачи, пиццы, "
            "мойки и хостес",
            False,
        ),
        ("Протереть все отпаренные зоны спецраствором", False),
        (
            "Пройтись щёткой (лежит слева от мойки, на стеллаже) по диванам "
            "и стульям",
            False,
        ),
        (
            "Выровнять стулья 100-го стола, засервировать стол ручниками, "
            "приборами и постановочными роксами",
            False,
        ),
        (
            "Протереть салфетницы (лежат в стейшене сверху слева) и пополнить "
            "их салфетками (салфетки лежат над мойкой)",
            False,
        ),
        (
            "Протереть кондименты (перечницы, солонки, соусники, сахарницы) "
            "тряпкой или влажной салфеткой",
            False,
        ),
        ("Протереть айки (антисептик + сухая тряпка)", False),
        ("Проверить наличие необходимого инвентаря для работы", False),
        (
            "По четвергам: пополнить солонки, перечницы, сахарницы и соусники, "
            "закрутить перчатки, привести в порядок станции официантов",
            False,
        ),
    ),
    "second": (
        ("Поднять жалюзи. Открыть окна ИЛИ включить кондиционеры", False),
        ("Протереть столы спецраствором", False),
        ("Накрутить ручники", False),
        ("Накрыть сервировку (ручники, приборы, роксы)", False),
        ("Пройтись щёткой по диванам и стульям", False),
        ("Взбить и поправить подушки", False),
        ("Выровнять все стулья в зале", False),
        ("Расставить вазы по своим местам", False),
        ("Протереть салфетницы и пополнить их", False),
        (
            "Протереть кондименты (перечницы, солонки, соусники, сахарницы)",
            False,
        ),
        ("Протереть айки (антисептик + сухая тряпка)", False),
        ("Проверить наличие необходимого инвентаря для начала работы", False),
        ("Аккуратно расставить посуду на стеллаже напротив мойки", False),
        (
            "По утрам понедельника сдать дощечки (для приборов и чеков) на мойку",
            False,
        ),
        ("По понедельникам и средам отпаривать столы", False),
        (
            "Вечером понедельника и вечером четверга полностью убирать "
            "сервировку со второго зала",
            False,
        ),
        (
            "По четвергам: пополнить солонки, перечницы, сахарницы и соусники, "
            "закрутить перчатки, привести в порядок станции официантов",
            False,
        ),
    ),
}

# Закрытие смены — общее для всех залов. Последний пункт — фотоотчёт рабочего
# места: его закрывают официанты и хостес.
_CLOSING: tuple[tuple[str, bool, str | None], ...] = (
    ("Убрать весь мусор из зала", False, None),
    ("Сдать все меню на позицию хостес", False, None),
    ("Протереть столы и станции официантов", False, None),
    (
        "Проверить, что все окна закрыты, жалюзи спущены, кондиционеры выключены",
        False,
        None,
    ),
    (
        "Во втором зале накрыть обязательную сервировку столов (кроме дней, "
        "когда её полностью убирают)",
        False,
        None,
    ),
    ("Показать рабочее место перед закрытием смены", True, None),
)

_HOSTESS_CLOSING: tuple[tuple[str, bool, str | None], ...] = (
    ("Принять меню у официантов и убрать на позицию хостес", False, None),
    ("Убрать мусор и привести в порядок зону хостес", False, None),
    (
        "Проверить, что окна закрыты, жалюзи спущены, кондиционеры выключены",
        False,
        None,
    ),
    ("Показать рабочее место перед закрытием смены", True, None),
)

_HOSTESS_SHIFT: tuple[tuple[str, bool, str | None], ...] = (
    ("Переодеться в рабочую форму", False, None),
    ("Открыть смену в iiko", False, None),
    ("Протереть стойку хостес и пополнить меню", False, None),
    ("Проверить брони и посадку на сегодня", False, None),
)

async def _ensure_hall(session: AsyncSession, slug: str, name: str, order: int) -> Hall:
    hall = await session.scalar(select(Hall).where(Hall.slug == slug))
    if hall is not None:
        return hall
    hall = Hall(name=name, slug=slug, sort_order=order)
    session.add(hall)
    await session.flush()
    return hall


async def _add_items(
    session: AsyncSession,
    template: ChecklistTemplate,
    items: tuple[tuple[str, bool, str | None], ...],
) -> None:
    for order, (title, requires_photo, condition) in enumerate(items):
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


async def seed_hall_checklists(session: AsyncSession) -> None:
    """Залы, открытие по залам и общее закрытие смены.

    Идемпотентно и аддитивно: на боевой базе создаёт только то, чего ещё нет.
    Если администратор уже завёл шаблоны под залы — ничего не трогаем.
    """
    halls = [await _ensure_hall(session, slug, name, order) for slug, name, order in _HALLS]

    waiter = await session.scalar(select(Department).where(Department.slug == "waiter"))
    if waiter is not None:
        existing = list(
            await session.scalars(
                select(ChecklistTemplate).where(
                    ChecklistTemplate.department_id == waiter.id,
                    ChecklistTemplate.kind == TEMPLATE_SHIFT,
                    ChecklistTemplate.hall_id.is_not(None),
                )
            )
        )
        if not existing:
            for hall in halls:
                items = _HALL_OPENING.get(hall.slug, ())
                if not items:
                    continue
                template = ChecklistTemplate(
                    department_id=waiter.id,
                    hall_id=hall.id,
                    title=f"Открытие — {hall.name}",
                    kind=TEMPLATE_SHIFT,
                    sort_order=hall.sort_order,
                )
                session.add(template)
                await session.flush()
                await _add_items(session, template, tuple((t, p, None) for t, p in items))

    # Хостес: отдельное подразделение и общий чек-лист закрытия с фотоотчётом.
    hostess = await session.scalar(
        select(Department).where(Department.slug == "hostess")
    )
    if hostess is None:
        hostess = Department(name="Хостес", slug="hostess", emoji="💁", sort_order=4)
        session.add(hostess)
        await session.flush()

    for dept, closing, shift_items in (
        (waiter, _CLOSING, None),
        (hostess, _HOSTESS_CLOSING, _HOSTESS_SHIFT),
    ):
        if dept is None:
            continue
        has_close = await session.scalar(
            select(ChecklistTemplate.id)
            .where(
                ChecklistTemplate.department_id == dept.id,
                ChecklistTemplate.kind == TEMPLATE_CLOSE,
            )
            .limit(1)
        )
        if has_close is None:
            template = ChecklistTemplate(
                department_id=dept.id,
                title="Закрытие смены",
                kind=TEMPLATE_CLOSE,
            )
            session.add(template)
            await session.flush()
            await _add_items(session, template, closing)

        if shift_items is not None:
            has_shift = await session.scalar(
                select(ChecklistTemplate.id)
                .where(
                    ChecklistTemplate.department_id == dept.id,
                    ChecklistTemplate.kind == TEMPLATE_SHIFT,
                )
                .limit(1)
            )
            if has_shift is None:
                template = ChecklistTemplate(
                    department_id=dept.id,
                    title=f"Чек-лист смены — {dept.name}",
                    kind=TEMPLATE_SHIFT,
                )
                session.add(template)
                await session.flush()
                await _add_items(session, template, shift_items)

    log.info("hr.seed_hall_checklists", halls=len(halls))


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


# Стартовая база стандартов: (заголовок, категория, инструкция, вопросы).
# Тексты намеренно короткие и про быт смены: их пишет не разработчик, а
# руководитель, а сид лишь показывает, как это выглядит и работает.
_STANDARDS: tuple[dict, ...] = (
    {
        "title": "Гигиена рук перед сменой",
        "emoji": "🧼",
        # Санитарный стандарт — обязательный: его пробел виден в отчёте смены.
        "is_required": True,
        "category": STANDARD_CATEGORY_SAFETY,
        "summary": "Когда мыть руки и сколько по времени",
        "body": (
            "1. Мойте руки до начала работы, после туалета, после денег и мусора.\n"
            "2. Намыливайте не меньше 20–30 секунд: ладони, между пальцами, \n"
            "   большие пальцы, под ногтями.\n"
            "3. Сушите одноразовым полотенцем, не об общий фартук.\n"
            "4. Перчатки — не замена мытью: их меняют после каждого перехода \n"
            "   между зонами (сырое → готовое)."
        ),
        "questions": (
            (
                "Сколько секунд нужно намыливать руки?",
                ("5–10 секунд", "Не меньше 20–30 секунд", "Достаточно сполоснуть"),
                1,
            ),
            (
                "Когда нужно менять перчатки?",
                (
                    "Раз в смену",
                    "После перехода между зонами и загрязнения",
                    "Только если порвались",
                ),
                1,
            ),
        ),
    },
    {
        "title": "Маркировка и сроки заготовок",
        "emoji": "🏷",
        "is_required": True,
        "category": STANDARD_CATEGORY_DISHES,
        "summary": "Что писать на этикетке и когда списывать",
        "body": (
            "1. На каждой заготовке — название, дата и время изготовления, \n"
            "   срок годности, кто сделал.\n"
            "2. Просроченное списываем сразу: не «докладываем» к свежему.\n"
            "3. Заготовка без маркировки считается просроченной.\n"
            "4. Проверка маркировок — обязательный пункт чек-листа смены."
        ),
        "questions": (
            (
                "Что делать с заготовкой без этикетки?",
                ("Использовать первой", "Считать просроченной и списать", "Спросить у коллеги"),
                1,
            ),
            (
                "Что обязательно указать на этикетке?",
                (
                    "Только название",
                    "Название, дату и время изготовления, срок годности и автора",
                    "Название и цену",
                ),
                1,
            ),
        ),
    },
    {
        "title": "Гость недоволен блюдом",
        "emoji": "🙋",
        "category": STANDARD_CATEGORY_SERVICE,
        "summary": "Как разговаривать и что фиксировать",
        "body": (
            "1. Выслушайте до конца, не спорьте и не оправдывайтесь.\n"
            "2. Скажите, что решите вопрос, и назовите срок («сейчас заменю»).\n"
            "3. Решение принимает менеджер смены: заменяем блюдо или убираем из \n"
            "   счёта — по правилам заведения.\n"
            "4. Заведите карточку в журнале проблем: категория «Гость», зона и \n"
            "   срочность. Без записи проблема повторится завтра."
        ),
        "questions": (
            (
                "Что сделать первым делом, когда гость недоволен?",
                (
                    "Объяснить, что блюдо приготовлено правильно",
                    "Выслушать до конца и назвать срок решения",
                    "Позвать другого официанта",
                ),
                1,
            ),
            (
                "Куда записать разбор ситуации с гостем?",
                ("Никуда, вопрос решён", "В журнал проблем карточкой", "В личные заметки"),
                1,
            ),
        ),
    },
    {
        "title": "Нож и оборудование: безопасность",
        "emoji": "🔪",
        "category": STANDARD_CATEGORY_EQUIPMENT,
        "summary": "Что проверить до работы и как себя вести",
        "body": (
            "1. Нож режет только на доске, лезвием от себя, не оставляйте его в \n"
            "   раковине.\n"
            "2. Перед включением оборудования проверьте шнур, кнопку стоп и \n"
            "   что кожух на месте.\n"
            "3. Не работайте с неисправным: сразу заводите карточку в журнале \n"
            "   проблем и сообщайте менеджеру.\n"
            "4. О порезе или травме немедленно говорите старшему смены — \n"
            "   журнал травм обязателен, даже если «не страшно»."
        ),
        "questions": (
            (
                "Нашли неисправный аппарат. Что делать?",
                (
                    "Починить самому по-быстрому",
                    "Не включать, завести карточку в журнале и сказать менеджеру",
                    "Отложить до конца смены",
                ),
                1,
            ),
            (
                "Порезался ножом. Что обязательно помимо обработки раны?",
                (
                    "Ничего, если порез небольшой",
                    "Сообщить старшему смены и зафиксировать",
                    "Уйти домой",
                ),
                1,
            ),
        ),
    },
)


async def seed_owners(session: AsyncSession) -> int:
    """Завести/дополнить профили владельцев проекта (плашка + роль `admin`).

    Идемпотентно и БЕЗ перезаписи того, что человек настроил сам: имя в `users`
    не трогаем (его может править бот), а у HR-профиля дописываем только плашку,
    роль и «знакомство пройдено». Без этого владелец попадал бы в поток
    первого запуска с вопросом «какое у тебя подразделение».

    Единственное исключение — ИСПОРЧЕННОЕ имя (U+FFFD в строке): такое нельзя
    восстановить декодированием, поэтому подставляем каноническое. Иначе в
    списках сотрудников и фильтрах ленты висели бы «ромбики» вместо имён
    разработчика и управляющего.
    """
    for tg_id, name, emoji, badge in OWNERS:
        user = await session.scalar(select(User).where(User.telegram_id == tg_id))
        if user is not None and display_names.is_corrupted(user.display_name):
            user.display_name = name
            log.info("hr.seed_owner_name_repaired", telegram_id=tg_id)
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


async def seed_standards(session: AsyncSession) -> int:
    """Стартовая база стандартов: инструкция + короткий тест на каждую.

    Как и остальной сид — только чтобы новый ресторан не открывал пустой
    экран; содержимое правит руководитель. Если стандарты уже есть, блок
    пропускается целиком (`count > 0`), поэтому переписанные тексты не
    затираются.
    """
    existing = await session.scalar(select(func.count()).select_from(Standard))
    if existing:
        return int(existing)

    for index, item in enumerate(_STANDARDS):
        standard = Standard(
            title=item["title"],
            emoji=item["emoji"],
            category=item["category"],
            summary=item["summary"],
            body=item["body"],
            department_id=None,
            pass_percent=DEFAULT_PASS_PERCENT,
            is_required=bool(item.get("is_required", False)),
            sort_order=index,
            is_active=True,
        )
        session.add(standard)
        await session.flush()
        for order, (text, options, correct) in enumerate(item["questions"]):
            session.add(
                StandardQuestion(
                    standard_id=standard.id,
                    text=text,
                    options=list(options),
                    correct_index=correct,
                    sort_order=order,
                )
            )
    await session.flush()
    log.info("hr.seed_standards", count=len(_STANDARDS))
    return len(_STANDARDS)


async def seed_hr(session: AsyncSession) -> None:
    """Один вход для lifespan: владельцы → подразделения → вопросы → ссылки → стандарты."""
    await seed_owners(session)
    await seed_departments(session)
    await seed_hall_checklists(session)
    await seed_feedback_questions(session)
    await seed_links(session)
    await seed_standards(session)
    await session.commit()
