"""Стартовые пакеты отрасли (B2B_PLATFORM_PLAN, фаза 3, шаг 3.2).

Зачем пакет, а не ещё пять настроек. Мастер настройки уже спрашивает отрасль,
но до сих пор ответ влиял только на подсказки подразделений: салон получал
«парикмахеров», а чек-листы, слова и цифры — ресторанные. Клиент видел, что
приложение всё равно про другое, и тратил первую неделю на переписывание
пяти экранов вручную.

Пакет — это **стартовый набор, а не шаблон продукта**. Он кладёт в организацию
то, что можно править: слова (`term.*` в `app_texts`), пару чек-листов
«открытие / закрытие» по подразделениям, веса опыта и подсказки должностей.
Ничего не блокируется и не перезаписывается задним числом: правка руководителя
всегда сильнее пакета.

Три правила, которые важнее содержимого:

* **применение идемпотентно.** Мастер можно пройти повторно, и второй проход не
  должен ни плодить чек-листы, ни возвращать удалённое, ни затирать переименованный
  «Кабинет» обратно в «Кабинет №1». Поэтому термины пишутся только туда, где
  правки ещё нет, а шаблоны — только туда, где шаблона нужного вида нет вовсе;
* **веса опыта не трогаем у работающей организации.** `admin_config` общий на
  установку (ключи без `org_id`), поэтому пакет меняет веса только когда их
  никто не задавал. Иначе салон, применённый вторым, пересчитал бы опыт
  ресторану — это уже не «стартовый набор», а чужая правка;
* **должности — подсказки, а не справочник.** В `employee.position` живёт
  свободный текст; пакет отдаёт список того, что в этой отрасли пишут чаще
  всего, чтобы человек не придумывал формулировку с нуля.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import app_texts, hr_checklists, hr_departments, hr_kpi
from app.services.hr_checklists import STARTER_CLOSING_ITEMS, STARTER_OPENING_ITEMS

# Пункт чек-листа: текст и нужно ли фото. Кортеж, а не dict: порядок пунктов —
# это порядок работы в смене, и он не должен зависеть от сортировки ключей.
PackItem = tuple[str, bool]

# Демо-роль: (подразделение, должность, плашка, эмодзи плашки). Подразделение —
# имя из пресетов отрасли, а не slug: в боевой организации slug получается
# `slugify(имя)`, и привязка по слагу из сида нашла бы разве что сидовые данные.
DemoRole = tuple[str, str, str, str]
DemoTask = tuple[str, bool]


@dataclass(frozen=True)
class IndustryPack:
    """Стартовый набор одной отрасли."""

    industry: str
    title: str
    # Одна фраза «зачем»: её читает руководитель на экране пакета.
    why: str
    # Слова, которые подставляются поверх дефолтов (`term.*`).
    terms: dict[str, str] = field(default_factory=dict)
    positions: tuple[str, ...] = ()
    opening: tuple[PackItem, ...] = ()
    closing: tuple[PackItem, ...] = ()
    # Веса опыта. Пустой словарь — «оставить как есть»: у универсального
    # пакета нет причин спорить с текущими правилами.
    kpi: dict[str, int] = field(default_factory=dict)
    # Состав витрины «покажем за 5 минут»: без него демо салона показывает
    # поваров и официантов, и клиент проверяет чужой продукт.
    demo_roles: tuple[DemoRole, ...] = ()
    demo_tasks: tuple[DemoTask, ...] = ()

    @property
    def checklist_items(self) -> int:
        return len(self.opening) + len(self.closing)


# --------------------------------------------------------------------------
# Сами пакеты
# --------------------------------------------------------------------------

_GENERIC = IndustryPack(
    industry="restaurant",
    title="Универсальный",
    why="Работа смены: открыть, проверить, закрыть. Подходит, если отрасль не выбрана.",
    opening=STARTER_OPENING_ITEMS,
    closing=STARTER_CLOSING_ITEMS,
)

PACKS: dict[str, IndustryPack] = {
    "restaurant": IndustryPack(
        industry="restaurant",
        title="Ресторан и кафе",
        why="Зал, смена и задача — слова кухни и зала; чек-листы про столы, витрину и кассу.",
        terms={},
        positions=("Официант", "Повар", "Бармен", "Хостес", "Менеджер смены"),
        opening=(
            ("Проверить чистоту зала и столов", True),
            ("Включить оборудование: кофемашина, витрина, касса", False),
            ("Проверить, что блюда из меню есть в наличии", False),
            ("Сверить брони и посадки на день", False),
            ("Проверить форму и внешний вид команды", False),
            ("Отметить начало смены в приложении", False),
        ),
        closing=(
            ("Убрать зал, вымыть столы и поверхности", True),
            ("Выключить оборудование, слить и промыть кофемашину", False),
            ("Закрыть кассу и сдать выручку", False),
            ("Внести, что закончилось на кухне и в баре", False),
        ),
        demo_roles=(
            ("Кухня", "повар", "Стажёр", "🌱"),
            ("Кухня", "су-шеф", "Су-шеф", "🍳"),
            ("Официанты", "официант", "Официант", "🍽"),
            ("Бар", "бармен", "Бармен", "🍸"),
            ("Менеджеры", "менеджер смены", "Менеджер", "📋"),
            ("Официанты", "официант", "Новичок", "🌱"),
        ),
        demo_tasks=(
            ("Проверить сроки годности на раздаче", True),
            ("Убрать кухонный инвентарь после закрытия", False),
            ("Обновить ценники в зале", False),
        ),
    ),
    "salon": IndustryPack(
        industry="salon",
        title="Салон красоты",
        why="Приёмы вместо смен, кабинеты вместо залов; чек-листы про инструмент, стерилизацию и запись.",
        terms={
            "term.hall.one": "Кабинет",
            "term.hall.many": "Кабинеты",
            "term.shift.one": "Приём",
            "term.shift.many": "Приёмы",
            "term.task.one": "Заявка",
            "term.task.many": "Заявки",
        },
        positions=("Парикмахер", "Мастер ногтей", "Косметолог", "Администратор"),
        opening=(
            ("Проверить чистоту кабинета и рабочего места", True),
            ("Проверить стерилизацию и исправность инструмента", False),
            ("Проверить расходники: краска, перчатки, полотенца", False),
            ("Сверить запись на день: кто, во сколько, какая услуга", False),
            ("Отметить начало приёма в приложении", False),
        ),
        closing=(
            ("Убрать кабинет, обработать и убрать инструмент", True),
            ("Выключить оборудование и свет", False),
            ("Внести, что закончилось и что нужно купить", False),
            ("Проверить запись на завтра и предупредить о переносах", False),
        ),
        # Приёмов в салоне много и они короткие: вес «смены» ниже, вес
        # поручения — выше, иначе опыт капал бы за сам факт рабочего дня.
        kpi={"xp_shift_done": 6, "xp_task": 12, "xp_on_time": 5, "min_xp_winner": 20},
        demo_roles=(
            ("Парикмахеры", "парикмахер", "Мастер", "✂️"),
            ("Парикмахеры", "парикмахер-стажёр", "Стажёр", "🌱"),
            ("Мастера ногтей", "мастер ногтей", "Нейл-мастер", "💅"),
            ("Косметологи", "косметолог", "Косметолог", "🧖"),
            ("Администраторы", "администратор", "Администратор", "🧾"),
            ("Администраторы", "менеджер смены", "Менеджер", "📋"),
        ),
        demo_tasks=(
            ("Подтвердить запись клиентов на завтра", False),
            ("Сфотографировать рабочее место до приёма", True),
            ("Проверить, что расходники на завтра есть", False),
        ),
    ),
    "autoservice": IndustryPack(
        industry="autoservice",
        title="Автосервис",
        why="Наряды вместо задач, посты вместо залов; чек-листы про оснастку, запчасти и машины в цеху.",
        terms={
            "term.hall.one": "Пост",
            "term.hall.many": "Посты",
            "term.shift.one": "Смена",
            "term.shift.many": "Смены",
            "term.task.one": "Наряд",
            "term.task.many": "Наряды",
        },
        positions=("Механик", "Мастер кузовного цеха", "Приёмщик", "Кладовщик"),
        opening=(
            ("Проверить подъёмники, оснастку и инструмент", False),
            ("Сверить заказ-наряды на день и готовность запчастей", False),
            ("Проверить чистоту постов и зоны приёмки", True),
            ("Проверить, что машины с вечера закрыты и подписаны", False),
            ("Отметить начало смены в приложении", False),
        ),
        closing=(
            ("Убрать инструмент по местам", True),
            ("Проверить, что машины в цеху закрыты", False),
            ("Внести замечания по машинам в наряды", False),
            ("Написать, что нужно закупить из расходников", False),
        ),
        # Наряд — основная единица работы и стоит дороже, чем в других
        # отраслях: за него отвечают деньгами клиента, а не галочкой.
        kpi={"xp_task": 20, "xp_on_time": 8, "xp_shift_done": 10, "min_xp_winner": 20},
        demo_roles=(
            ("Механики", "механик", "Механик", "🔧"),
            ("Механики", "автослесарь", "Стажёр", "🌱"),
            ("Кузовной цех", "мастер кузовного цеха", "Кузовной", "🚗"),
            ("Приёмка", "приёмщик", "Приёмщик", "🧾"),
            ("Склад", "кладовщик", "Склад", "📦"),
            ("Механики", "бригадир", "Бригадир", "📋"),
        ),
        demo_tasks=(
            ("Сфотографировать машину при приёмке", True),
            ("Заказать запчасти по наряду", False),
            ("Проверить, что инструмент вернули на место", False),
        ),
    ),
    "retail": IndustryPack(
        industry="retail",
        title="Розница",
        why="Отделы вместо залов, заявки вместо задач; чек-листы про выкладку, ценники и кассу.",
        terms={
            "term.hall.one": "Отдел",
            "term.hall.many": "Отделы",
            "term.shift.one": "Смена",
            "term.shift.many": "Смены",
            "term.task.one": "Заявка",
            "term.task.many": "Заявки",
        },
        positions=("Продавец", "Кассир", "Кладовщик", "Управляющий"),
        opening=(
            ("Открыть отдел: свет, касса, терминал", False),
            ("Проверить выкладку и ценники", True),
            ("Проверить, что товар на полке есть на складе", False),
            ("Сверить размен в кассе", False),
            ("Отметить начало смены в приложении", False),
        ),
        closing=(
            ("Закрыть кассу и сдать выручку", False),
            ("Проверить зал и выкладку к завтрашнему дню", True),
            ("Внести, что закончилось на полке", False),
            ("Выключить свет и оборудование", False),
        ),
        kpi={"xp_shift_done": 8, "xp_task": 12, "xp_on_time": 5, "min_xp_winner": 20},
        demo_roles=(
            ("Торговый зал", "продавец", "Продавец", "🛍"),
            ("Торговый зал", "продавец-стажёр", "Стажёр", "🌱"),
            ("Касса", "кассир", "Кассир", "💳"),
            ("Склад", "кладовщик", "Склад", "📦"),
            ("Управляющие", "управляющий", "Управляющий", "📋"),
            ("Торговый зал", "мерчендайзер", "Выкладка", "🧺"),
        ),
        demo_tasks=(
            ("Выложить новую поставку", True),
            ("Переклеить ценники на акцию", False),
            ("Проверить сроки годности на полке", False),
        ),
    ),
}

# `cafe` в мастер-настройке есть отдельно, но отличается он подразделениями, а
# не словами и чек-листами: витрина, кофемашина, касса — тот же ресторанный
# старт. Держим алиас, чтобы не заводить второй почти такой же список.
_ALIASES: dict[str, str] = {"cafe": "restaurant", "other": "restaurant"}


def get(industry: str | None) -> IndustryPack:
    """Пакет отрасли. Неизвестная отрасль — универсальный, а не ошибка."""
    key = _ALIASES.get((industry or "").strip().lower(), (industry or "").strip().lower())
    return PACKS.get(key, _GENERIC)


def known(industry: str | None) -> bool:
    """Есть ли для этой отрасли свой пакет (алиасы считаются своими).

    Проверка нужна ручке: прислать `industry=starship` не должно означать
    «молча примени универсальный», иначе ошибка клиента выглядит как успех.
    """
    key = (industry or "").strip().lower()
    return key in PACKS or key in _ALIASES


def demo_roster(industry: str | None) -> tuple[DemoRole, ...]:
    """Кого показывать в демо для этой отрасли.

    Универсальный пакет демо-состава не задаёт (он и есть ресторанный фолбэк),
    поэтому пустой список здесь означает «взять ресторанный» — иначе витрина
    у установки без отрасли осталась бы без людей.
    """
    pack = get(industry)
    return pack.demo_roles or PACKS["restaurant"].demo_roles


def demo_tasks(industry: str | None) -> tuple[DemoTask, ...]:
    """Поручения демо для этой отрасли. Пусто — ресторанные, как и с ролями."""
    pack = get(industry)
    return pack.demo_tasks or PACKS["restaurant"].demo_tasks


def all_packs() -> list[IndustryPack]:
    """Каталог для экрана «Пакет отрасли» — в стабильном порядке."""
    return [_GENERIC, *[PACKS[key] for key in ("salon", "autoservice", "retail")]]


@dataclass
class Applied:
    """Что пакет реально изменил.

    Счётчики, а не True: «применил» без чисел не отличает «сделал» от «всё уже
    было», и руководитель не понимает, нажатие сработало или нет.
    """

    industry: str
    terms_set: int = 0
    templates_created: int = 0
    kpi_updated: bool = False
    force: bool = False


async def apply(
    session: AsyncSession,
    *,
    industry: str | None,
    force_terms: bool = False,
) -> Applied:
    """Применить пакет к текущей организации.

    Порядок шагов не случайный. Термины — первыми: если дальше упадёт создание
    шаблонов, слова всё равно уже соответствуют отрасли, а повторный вызов
    доберёт остальное (всё идемпотентно).

    `force_terms` перезаписывает даже уже переименованное. Это отдельное
    действие: молча вернуть «Зал» поверх «Кабинета» — ровно тот сюрприз, из-за
    которого перестают доверять настройкам.
    """
    pack = get(industry)

    terms_set = 0
    if pack.terms:
        current = await app_texts.overrides(session)
        patch = {
            code: value
            for code, value in pack.terms.items()
            if force_terms or not (current.get(code) or "").strip()
        }
        if patch:
            await app_texts.save(session, patch)
            terms_set = len(patch)

    created = 0
    departments = await hr_departments.list_departments(session, active_only=False)
    # Пустой список подразделений — не повод молчать с пустыми экранами: пакет
    # заводит одно «Общее», и чек-листы появляются вместе с ним. Так же
    # поступает мастер настройки, и повторное применение уже ничего не создаст.
    if not departments:
        await hr_departments.create_department(session, name="Общее", emoji="🏢")
        departments = await hr_departments.list_departments(session, active_only=False)
    for department in departments:
        created += len(
            await hr_checklists.ensure_templates(
                session,
                department_id=department.id,
                opening=pack.opening or STARTER_OPENING_ITEMS,
                closing=pack.closing or STARTER_CLOSING_ITEMS,
            )
        )

    kpi_updated = False
    if pack.kpi and not await _kpi_touched(session):
        # Только «с чистого листа»: веса общие на установку, и правка одного
        # клиента не должна переезжать к другому.
        await hr_kpi.update_rules(session, **pack.kpi)
        kpi_updated = True

    return Applied(
        industry=pack.industry,
        terms_set=terms_set,
        templates_created=created,
        kpi_updated=kpi_updated,
        force=force_terms,
    )


async def _kpi_touched(session: AsyncSession) -> bool:
    """Задавал ли кто-то веса опыта руками.

    Читаем ключи `hr_kpi` напрямую: `get_rules` возвращает значения по умолчанию
    и не отличает «не настраивали» от «настроили ровно как по умолчанию».
    """
    from sqlalchemy import select

    from app.db.models import AdminConfig

    keys = (
        hr_kpi.KEY_XP_CHECKLIST_ITEM,
        hr_kpi.KEY_XP_SHIFT_DONE,
        hr_kpi.KEY_XP_TASK,
        hr_kpi.KEY_XP_ON_TIME,
        hr_kpi.KEY_MIN_XP_FOR_WINNER,
    )
    row = await session.scalar(
        select(AdminConfig.key).where(AdminConfig.key.in_(keys)).limit(1)
    )
    return row is not None


def summary(pack: IndustryPack) -> dict[str, object]:
    """Пакет в виде, пригодном для JSON: без внутренних кортежей."""
    return {
        "industry": pack.industry,
        "title": pack.title,
        "why": pack.why,
        "terms": dict(pack.terms),
        "positions": list(pack.positions),
        "checklist_items": pack.checklist_items,
        "opening_items": [title for title, _ in pack.opening],
        "closing_items": [title for title, _ in pack.closing],
        "kpi": dict(pack.kpi),
        "demo_roles": [
            {
                "department": department,
                "position": position,
                "badge": badge,
                "emoji": emoji,
            }
            for department, position, badge, emoji in pack.demo_roles
        ],
        "demo_tasks": [
            {"title": title, "photo": photo} for title, photo in pack.demo_tasks
        ],
    }
