"""Меню смены: сотрудник читает, руководитель правит прямо в приложении.

Раньше меню приходило снимком Google Sheets вместе с графиком: чтобы убрать
блюдо, нужно было открыть таблицу и дождаться обновления копии на сервере.
Теперь меню — собственные данные организации, а снимок таблицы остаётся для
графика и методичек, где ручная правка не нужна.

Права разделены так же, как везде в проекте: читать может любой сотрудник,
править — `aup` и админ. Позиции «нет в наличии» (стоп-лист) сотруднику
отдаются: официанту нужно знать, что блюдо кончилось, — иначе он продаёт его
и дальше. Отличаются они пометкой `is_available`, а не отсутствием в ответе.

Почему не скрываем. До стоп-листа скрытая позиция означала «сегодня этого
нет», и сотруднику её не показывали вовсе. Но именно он и стоит у гостя:
пустой список молчит, а плашка «нет в наличии» отвечает на вопрос. Поэтому
решение принимает тот, кто смотрит (`is_available`), а не фильтр выдачи.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import AupDep, EmployeeDep, OrgDep, SessionDep
from app.db.hr_models import DEFAULT_MENU_CATEGORY, MenuItem
from app.db.org_models import Organization
from app.services import hr_media, hr_menu

router = APIRouter(tags=["menu"])


class MenuItemOut(BaseModel):
    id: int
    name: str
    category: str
    description: str | None
    price_rub: int | None
    # Ссылка на снимок блюда — подписанная, как у фотоотчётов. Отдаём и id:
    # без него клиент не сможет отправить обратно «это же фото» при правке
    # других полей, а гонять байты картинки ради этого незачем.
    photo_blob_id: int | None
    photo_url: str | None
    is_available: bool
    sort_order: int
    updated_at: datetime | None


class MenuOut(BaseModel):
    items: list[MenuItemOut]
    # Порядок групп задаёт выдача; фронт не сортирует повторно, чтобы подписи
    # групп и строки не разъехались.
    categories: list[str]
    # Сколько позиций в стоп-листе. Нужно обеим ролям: сотруднику — чтобы
    # понять, что наверху списка не всё, руководителю — чтобы видеть объём.
    stopped: int
    # Валюта цен организации: «320» без неё не говорит ничего. Приходит вместе
    # с меню, чтобы клиент не делал второй запрос ради одной подписи.
    currency: str


def _out(item: MenuItem) -> MenuItemOut:
    return MenuItemOut(
        id=item.id,
        name=item.name,
        category=item.category or DEFAULT_MENU_CATEGORY,
        description=item.description,
        price_rub=item.price_rub,
        photo_blob_id=item.photo_blob_id,
        photo_url=(
            hr_media.url_for(int(item.photo_blob_id))
            if item.photo_blob_id is not None
            else None
        ),
        is_available=item.is_available,
        sort_order=item.sort_order,
        updated_at=item.updated_at,
    )


@router.get("/menu", response_model=MenuOut)
async def list_menu(
    session: SessionDep, _: EmployeeDep, org: OrgDep
) -> MenuOut:
    """Меню смены целиком: и то, что есть, и стоп-лист с пометкой.

    Фильтр «только в наличии» — дело клиента: один и тот же ответ рисует и
    экран сотрудника, и кабинет руководителя, а роль меняет только наличие
    кнопок правки.
    """
    items = await hr_menu.list_items(session)
    return MenuOut(
        items=[_out(item) for item in items],
        categories=hr_menu.categories_of(items),
        stopped=sum(1 for item in items if not item.is_available),
        currency=_currency_of(org),
    )


def _currency_of(org: Organization | None) -> str:
    """Валюта организации или рубль, если организации в запросе нет.

    `None` бывает только в тестах и служебных вызовах: у настоящего запроса
    организация всегда есть, иначе некому показывать меню.
    """
    raw = (getattr(org, "currency", None) or hr_menu.CURRENCY_DEFAULT).strip()
    return raw.upper() or hr_menu.CURRENCY_DEFAULT


class CurrencyIn(BaseModel):
    currency: str = Field(min_length=3, max_length=3)


class CurrencyOut(BaseModel):
    currency: str


@router.patch("/menu/currency", response_model=CurrencyOut)
async def set_menu_currency(
    body: CurrencyIn, session: SessionDep, org: OrgDep, _: AupDep
) -> CurrencyOut:
    """Валюта цен — один раз на организацию, а не поле каждой позиции.

    Меню не может быть в двух валютах одновременно: официант называет одну
    цену гостю. Поэтому валюта лежит в организации, а ручка живёт рядом с
    меню — там, где руководитель её и ищет.
    """
    try:
        code = hr_menu.clean_currency(body.currency)
    except hr_menu.MenuError as exc:
        raise _bad_request(exc) from exc
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="org_not_found")
    org.currency = code
    await session.commit()
    return CurrencyOut(currency=code)


class MenuItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=hr_menu.MAX_NAME)
    category: str = Field(
        default=DEFAULT_MENU_CATEGORY, max_length=hr_menu.MAX_CATEGORY
    )
    description: str | None = Field(None, max_length=hr_menu.MAX_DESCRIPTION)
    price_rub: int | None = Field(None, ge=0, le=hr_menu.MAX_PRICE_RUB)
    photo_blob_id: int | None = Field(None, ge=1)
    sort_order: int = 0
    is_available: bool = True


class MenuItemPatch(BaseModel):
    """Частичная правка. Отсутствующее поле не трогаем, `null` — очищаем."""

    name: str | None = Field(None, min_length=1, max_length=hr_menu.MAX_NAME)
    category: str | None = Field(None, max_length=hr_menu.MAX_CATEGORY)
    description: str | None = Field(None, max_length=hr_menu.MAX_DESCRIPTION)
    price_rub: int | None = Field(None, ge=0, le=hr_menu.MAX_PRICE_RUB)
    photo_blob_id: int | None = Field(None, ge=1)
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
            photo_blob_id=body.photo_blob_id,
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
