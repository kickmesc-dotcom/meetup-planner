"""Меню смены: позиции, которые руководитель правит прямо в приложении.

Почему не только Google Sheets. Меню меняется каждый день и часто в последнюю
минуту: закончилась рыба, поменялась цена, добавили сезонное. Пока меню жило
только в таблице, любая такая правка означала «открыть Google с телефона,
найти лист, дождаться, пока сервер перезаберёт CSV». Ночью, в смену, это не
выполняется — меню оставалось вчерашним.

Правила здесь простые и намеренно узкие:

* всё, что попадает в базу, обрезается по краям и ограничено по длине — иначе
  в меню появляется строка из 4000 символов, и карточка ломает вёрстку;
* цена — целые рубли, `None` означает «по запросу»; отрицательной цены не
  бывает, а «999999999» — это опечатка, а не прайс;
* удаление отдельно от «нет в наличии»: скрытая позиция остаётся в меню и
  возвращается одним нажатием, удалённая — нет.

Права проверяет API (`require_aup`), а не сервис: сервис вызывается и из
тестов, и из будущих сценариев (импорт, копирование меню), где сотрудник
может быть не при чём.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import DEFAULT_MENU_CATEGORY, Employee, MenuItem

# Границы полей. Держим здесь, а не в схемах API: те же числа нужны и валидации
# Pydantic, и сервису (который зовут без Pydantic), и тестам.
MAX_NAME = 160
MAX_CATEGORY = 64
MAX_DESCRIPTION = 300
MAX_PRICE_RUB = 1_000_000

# «Не менять поле» в частичной правке. Отличается от `None`, потому что `None`
# в цене и описании — это осознанное «очистить», а не «оставить как было».
UNSET: Any = object()


class MenuError(Exception):
    """Отказ с кодом для API. Текст кода уходит в `detail` и переводится на фронте."""


def clean_name(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        raise MenuError("name_required")
    if len(text) > MAX_NAME:
        raise MenuError("name_too_long")
    return text


def clean_category(value: str | None) -> str:
    """Пустая категория — не ошибка, а «в общем списке»."""
    text = (value or "").strip() or DEFAULT_MENU_CATEGORY
    if len(text) > MAX_CATEGORY:
        raise MenuError("category_too_long")
    return text


def clean_description(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if len(text) > MAX_DESCRIPTION:
        raise MenuError("description_too_long")
    return text


def clean_price(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        # `True` — это int в Python; в цене он означает ошибку клиента, а не 1 ₽.
        raise MenuError("bad_price")
    if value < 0:
        raise MenuError("price_negative")
    if value > MAX_PRICE_RUB:
        raise MenuError("price_too_high")
    return value


def clean_sort_order(value: int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise MenuError("bad_sort_order")
    # Порядок — подсказка для сортировки, а не данные: огромное число просто
    # уводит позицию в конец, и спорить с ним незачем.
    return max(-100_000, min(100_000, value))


async def list_items(
    session: AsyncSession, *, include_unavailable: bool = True
) -> list[MenuItem]:
    """Позиции меню в порядке показа: группа, затем порядок внутри группы.

    Сотруднику (`include_unavailable=False`) недоступное не показываем вовсе:
    «нет в наличии» на его экране — это шум, ему нечего с этим делать.
    """
    stmt = select(MenuItem)
    if not include_unavailable:
        stmt = stmt.where(MenuItem.is_available.is_(True))
    stmt = stmt.order_by(MenuItem.category, MenuItem.sort_order, MenuItem.id)
    return list((await session.scalars(stmt)).all())


async def get_item(session: AsyncSession, item_id: int) -> MenuItem | None:
    return await session.get(MenuItem, item_id)


def categories_of(items: list[MenuItem]) -> list[str]:
    """Порядок групп — как в выдаче, без повторов и без пустых подписей."""
    seen: list[str] = []
    for item in items:
        name = (item.category or DEFAULT_MENU_CATEGORY).strip() or DEFAULT_MENU_CATEGORY
        if name not in seen:
            seen.append(name)
    return seen


async def create_item(
    session: AsyncSession,
    *,
    name: str,
    category: str | None = None,
    description: str | None = None,
    price_rub: int | None = None,
    sort_order: int | None = 0,
    is_available: bool = True,
    employee: Employee | None = None,
) -> MenuItem:
    item = MenuItem(
        name=clean_name(name),
        category=clean_category(category),
        description=clean_description(description),
        price_rub=clean_price(price_rub),
        sort_order=clean_sort_order(sort_order),
        is_available=bool(is_available),
        updated_by_employee_id=employee.id if employee is not None else None,
    )
    session.add(item)
    await session.flush()
    return item


async def update_item(
    session: AsyncSession,
    item: MenuItem,
    *,
    name: Any = UNSET,
    category: Any = UNSET,
    description: Any = UNSET,
    price_rub: Any = UNSET,
    sort_order: Any = UNSET,
    is_available: Any = UNSET,
    employee: Employee | None = None,
) -> MenuItem:
    """Частичная правка: меняем только переданные поля.

    Так «убрать из меню на сегодня» — это одно поле, и оно не может случайно
    переписать название или цену (самый дорогой вид опечатки в меню).
    """
    if name is not UNSET:
        item.name = clean_name(name)
    if category is not UNSET:
        item.category = clean_category(category)
    if description is not UNSET:
        item.description = clean_description(description)
    if price_rub is not UNSET:
        item.price_rub = clean_price(price_rub)
    if sort_order is not UNSET:
        item.sort_order = clean_sort_order(sort_order)
    if is_available is not UNSET:
        item.is_available = bool(is_available)
    if employee is not None:
        item.updated_by_employee_id = employee.id
    await session.flush()
    return item


async def delete_item(session: AsyncSession, item: MenuItem) -> None:
    await session.delete(item)
    await session.flush()
