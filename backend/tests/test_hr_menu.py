"""Меню смены: правила правки и операции над позициями.

Что здесь проверяем и почему именно это:

* **частичная правка не затирает остальные поля.** Самый дорогой вид опечатки
  в меню — «убрал позицию на сегодня» и заодно обнулил цену. Поэтому PATCH
  собран так, чтобы менять только переданное;
* **«нет в наличии» — не удаление.** Скрытая позиция должна возвращаться одним
  нажатием, иначе руководитель заводит её заново с нуля;
* **сотрудник не видит скрытое.** Для него это шум: сделать он с этим ничего
  не может;
* **мусор в цене не доходит до базы.** Отрицательная цена и «999 999 999» —
  это опечатка, а не прайс.

Env выставляем ДО импорта моделей — `Settings` требует BOT_TOKEN и т.п.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.hr_models import DEFAULT_MENU_CATEGORY, MenuItem  # noqa: E402
from app.services import hr_menu  # noqa: E402


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: MenuItem.__table__.create(c))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


# --------------------------------------------------------------------------
# Чистка полей
# --------------------------------------------------------------------------


def test_name_is_trimmed_and_required() -> None:
    assert hr_menu.clean_name("  Борщ  ") == "Борщ"
    with pytest.raises(hr_menu.MenuError):
        hr_menu.clean_name("   ")
    with pytest.raises(hr_menu.MenuError):
        hr_menu.clean_name("я" * (hr_menu.MAX_NAME + 1))


def test_empty_category_falls_back_to_default() -> None:
    # Пустая категория — не ошибка: заведение без групп не должно спотыкаться.
    assert hr_menu.clean_category(None) == DEFAULT_MENU_CATEGORY
    assert hr_menu.clean_category("  ") == DEFAULT_MENU_CATEGORY
    assert hr_menu.clean_category(" Бар ") == "Бар"


def test_price_rejects_negative_and_absurd_values() -> None:
    assert hr_menu.clean_price(None) is None
    assert hr_menu.clean_price(0) == 0
    assert hr_menu.clean_price(450) == 450
    with pytest.raises(hr_menu.MenuError):
        hr_menu.clean_price(-1)
    with pytest.raises(hr_menu.MenuError):
        hr_menu.clean_price(hr_menu.MAX_PRICE_RUB + 1)
    # `True` — это int в Python, но в цене это ошибка клиента, а не 1 ₽.
    with pytest.raises(hr_menu.MenuError):
        hr_menu.clean_price(True)  # type: ignore[arg-type]


def test_description_is_optional_and_trimmed() -> None:
    assert hr_menu.clean_description("   ") is None
    assert hr_menu.clean_description("  со сметаной ") == "со сметаной"
    with pytest.raises(hr_menu.MenuError):
        hr_menu.clean_description("я" * (hr_menu.MAX_DESCRIPTION + 1))


# --------------------------------------------------------------------------
# Хранение
# --------------------------------------------------------------------------


async def test_created_items_are_grouped_and_ordered(session) -> None:
    await hr_menu.create_item(session, name="Стейк", category="Горячее", sort_order=2)
    await hr_menu.create_item(session, name="Паста", category="Горячее", sort_order=1)
    await hr_menu.create_item(session, name="Чай", category="Напитки")

    items = await hr_menu.list_items(session)
    assert [i.name for i in items] == ["Паста", "Стейк", "Чай"]
    assert hr_menu.categories_of(items) == ["Горячее", "Напитки"]


async def test_partial_update_keeps_other_fields(session) -> None:
    item = await hr_menu.create_item(
        session, name="Борщ", category="Супы", price_rub=320, description="с пампушкой"
    )
    await hr_menu.update_item(session, item, is_available=False)

    assert item.is_available is False
    # Главное: цена, имя и описание остались прежними.
    assert (item.name, item.price_rub, item.description) == (
        "Борщ",
        320,
        "с пампушкой",
    )


async def test_price_can_be_cleared_explicitly(session) -> None:
    item = await hr_menu.create_item(session, name="Сезонное", price_rub=500)
    await hr_menu.update_item(session, item, price_rub=None)
    assert item.price_rub is None


async def test_staff_list_skips_unavailable_items(session) -> None:
    await hr_menu.create_item(session, name="Борщ", price_rub=320)
    gone = await hr_menu.create_item(session, name="Рыба", price_rub=690)
    await hr_menu.update_item(session, gone, is_available=False)

    for_manager = await hr_menu.list_items(session, include_unavailable=True)
    for_staff = await hr_menu.list_items(session, include_unavailable=False)
    assert [i.name for i in for_manager] == ["Борщ", "Рыба"]
    assert [i.name for i in for_staff] == ["Борщ"]


async def test_update_rejects_bad_price_without_touching_the_row(session) -> None:
    item = await hr_menu.create_item(session, name="Борщ", price_rub=320)
    with pytest.raises(hr_menu.MenuError):
        await hr_menu.update_item(session, item, price_rub=-5)
    assert item.price_rub == 320


async def test_delete_removes_the_row(session) -> None:
    item = await hr_menu.create_item(session, name="Борщ")
    await hr_menu.delete_item(session, item)
    assert await hr_menu.list_items(session) == []
    assert await hr_menu.get_item(session, item.id) is None
