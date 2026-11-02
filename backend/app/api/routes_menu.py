"""Меню смены: сотрудник читает, руководитель правит прямо в приложении.

Раньше меню приходило снимком Google Sheets вместе с графиком: чтобы убрать
блюдо, нужно было открыть таблицу и дождаться обновления копии на сервере.
Теперь меню — собственные данные организации, а снимок таблицы остаётся для
графика и методичек, где ручная правка не нужна.

Права разделены так же, как везде в проекте: читать может любой сотрудник
(он в ответе видит только то, что сегодня есть), править — `aup` и админ.
Скрытые позиции сотруднику не отдаются вовсе: для него «нет в наличии» — шум.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import AupDep, EmployeeDep, SessionDep
from app.db.hr_models import DEFAULT_MENU_CATEGORY, MenuItem
from app.services import hr_access, hr_menu

router = APIRouter(tags=["menu"])


class MenuItemOut(BaseModel):
    id: int
    name: str
    category: str
    description: str | None
    price_rub: int | None
    is_available: bool
    sort_order: int
    updated_at: datetime | None


class MenuOut(BaseModel):
    items: list[MenuItemOut]
    # Порядок групп задаёт выдача; фронт не сортирует повторно, чтобы подписи
    # групп и строки не разъехались.
    categories: list[str]
    # Сколько позиций сейчас «нет в наличии». Сотруднику всегда 0: он их не видит.
    hidden: int


def _out(item: MenuItem) -> MenuItemOut:
    return MenuItemOut(
        id=item.id,
        name=item.name,
        category=item.category or DEFAULT_MENU_CATEGORY,
        description=item.description,
        price_rub=item.price_rub,
        is_available=item.is_available,
        sort_order=item.sort_order,
        updated_at=item.updated_at,
    )


@router.get("/menu", response_model=MenuOut)
async def list_menu(session: SessionDep, employee: EmployeeDep) -> MenuOut:
    """Меню смены. Руководитель видит и скрытые позиции, чтобы вернуть их."""
    manage = hr_access.is_aup(employee)
    items = await hr_menu.list_items(session, include_unavailable=manage)
    return MenuOut(
        items=[_out(item) for item in items],
        categories=hr_menu.categories_of(items),
        hidden=sum(1 for item in items if not item.is_available),
    )


class MenuItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=hr_menu.MAX_NAME)
    category: str = Field(
        default=DEFAULT_MENU_CATEGORY, max_length=hr_menu.MAX_CATEGORY
    )
    description: str | None = Field(None, max_length=hr_menu.MAX_DESCRIPTION)
    price_rub: int | None = Field(None, ge=0, le=hr_menu.MAX_PRICE_RUB)
    sort_order: int = 0
    is_available: bool = True


class MenuItemPatch(BaseModel):
    """Частичная правка. Отсутствующее поле не трогаем, `null` — очищаем."""

    name: str | None = Field(None, min_length=1, max_length=hr_menu.MAX_NAME)
    category: str | None = Field(None, max_length=hr_menu.MAX_CATEGORY)
    description: str | None = Field(None, max_length=hr_menu.MAX_DESCRIPTION)
    price_rub: int | None = Field(None, ge=0, le=hr_menu.MAX_PRICE_RUB)
    sort_order: int | None = None
    is_available: bool | None = None


def _bad_request(exc: hr_menu.MenuError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/menu", response_model=MenuItemOut, status_code=201)
async def create_menu_item(
    body: MenuItemIn, session: SessionDep, employee: AupDep
) -> MenuItemOut:
    try:
        item = await hr_menu.create_item(
            session,
            name=body.name,
            category=body.category,
            description=body.description,
            price_rub=body.price_rub,
            sort_order=body.sort_order,
            is_available=body.is_available,
            employee=employee,
        )
    except hr_menu.MenuError as exc:
        await session.rollback()
        raise _bad_request(exc) from exc
    await session.commit()
    await session.refresh(item)
    return _out(item)


@router.patch("/menu/{item_id}", response_model=MenuItemOut)
async def patch_menu_item(
    item_id: int,
    body: MenuItemPatch,
    session: SessionDep,
    employee: AupDep,
) -> MenuItemOut:
    item = await hr_menu.get_item(session, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="menu_item_not_found")

    # `exclude_unset` — суть частичной правки: «нет в наличии» не должно
    # отправлять заодно цену и описание, которых в запросе не было.
    payload = body.model_dump(exclude_unset=True)
    try:
        await hr_menu.update_item(session, item, employee=employee, **payload)
    except hr_menu.MenuError as exc:
        await session.rollback()
        raise _bad_request(exc) from exc
    await session.commit()
    await session.refresh(item)
    return _out(item)


@router.delete("/menu/{item_id}", status_code=204)
async def delete_menu_item(
    item_id: int, session: SessionDep, _: AupDep
) -> None:
    item = await hr_menu.get_item(session, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="menu_item_not_found")
    await hr_menu.delete_item(session, item)
    await session.commit()
