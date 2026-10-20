"""Ручки редактируемых текстов приложения.

* `GET /api/texts` — карта «код → текст» для мини-аппа. Открытая: это подписи
  интерфейса, секретов в них нет, а читать их нужно до всякой авторизации.
* `GET /api/admin/texts` — каталог с дефолтами и текущими значениями.
* `PUT /api/admin/texts` — сохранить правки (пустая строка возвращает дефолт).

Почему отдельный роутер, а не `routes_admin`: тот разросся наследными
шуточными модулями, которые мы постепенно снимаем. Тексты — рабочая функция
продукта, и ей нужен свой, читаемый дом.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import AdminDep, SessionDep
from app.services import app_texts

router = APIRouter(tags=["texts"])


class TextItemOut(BaseModel):
    code: str
    group: str
    title: str
    hint: str
    default: str
    value: str


class TextsCatalogOut(BaseModel):
    items: list[TextItemOut]
    overrides: dict[str, str]


@router.get("/texts")
async def public_texts(session: SessionDep) -> dict[str, str]:
    """Тексты для интерфейса. Без авторизации — это статические подписи."""
    return await app_texts.effective(session)


@router.get("/admin/texts", response_model=TextsCatalogOut)
async def admin_texts(session: SessionDep, _: AdminDep) -> TextsCatalogOut:
    effective = await app_texts.effective(session)
    overrides = await app_texts.overrides(session)
    return TextsCatalogOut(
        items=[
            TextItemOut(
                code=spec.code,
                group=spec.group,
                title=spec.title,
                hint=spec.hint,
                default=spec.default,
                value=effective[spec.code],
            )
            for spec in app_texts.CATALOG
        ],
        overrides=overrides,
    )


@router.put("/admin/texts", response_model=TextsCatalogOut)
async def admin_save_texts(
    body: dict[str, str], session: SessionDep, _: AdminDep
) -> TextsCatalogOut:
    """Правки слиянием: пустая строка — «вернуть как было».

    Коды, которых нет в теле, не трогаем — фронт присылает только изменённое.
    """
    try:
        effective = await app_texts.save(session, body)
    except app_texts.TextsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    overrides = await app_texts.overrides(session)
    return TextsCatalogOut(
        items=[
            TextItemOut(
                code=spec.code,
                group=spec.group,
                title=spec.title,
                hint=spec.hint,
                default=spec.default,
                value=effective[spec.code],
            )
            for spec in app_texts.CATALOG
        ],
        overrides=overrides,
    )


__all__ = ["router"]
