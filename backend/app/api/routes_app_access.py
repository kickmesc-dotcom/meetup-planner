"""Ссылки входа в веб-версию: выпуск, список, отзыв.

Ручки живут в `/api/me/access-links`, потому что это личные ссылки человека, а
не админская настройка. Правила:

* `GET` — можно и по ссылке доступа: человек должен видеть выданные ссылки,
  чтобы заметить чужой вход;
* `POST`/`DELETE` — **только с `initData`**, то есть из Telegram. Иначе
  украденный токен продлевал бы сам себя: отозвали ссылку — а он выпустил
  новую. Проверка `telegram_only` стоит отдельной зависимостью, до всякой
  работы с базой.

Ответ на выпуск — единственное место, где виден сам токен. В списке его нет
никогда: только даты и признак «жива».
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.services import app_access

router = APIRouter(prefix="/me/access-links", tags=["app-access"])

LINK_HINT = "Открыть на компьютере"


async def telegram_only(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Выпуск и отзыв — только из мини-аппа (есть подпись Telegram).

    Отдельная зависимость, а не проверка внутри тела: так она срабатывает
    раньше, и в логах видно отказ до обращения к БД.
    """
    if not authorization:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="telegram_only")


TelegramOnly = Annotated[None, Depends(telegram_only)]


class AccessLinkOut(BaseModel):
    id: int
    label: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    is_active: bool
    is_current: bool = False


class AccessLinkCreated(BaseModel):
    id: int
    url: str
    expires_at: datetime


class AccessLinkIn(BaseModel):
    label: str = Field(default=LINK_HINT, max_length=80)


def _out(link: app_access.AppAccessLink, *, current: bool = False) -> AccessLinkOut:
    return AccessLinkOut(
        id=link.id,
        label=link.label,
        created_at=link.created_at,
        expires_at=link.expires_at,
        last_used_at=link.last_used_at,
        is_active=app_access.is_active(link),
        is_current=current,
    )


@router.get("", response_model=list[AccessLinkOut])
async def list_links(
    session: SessionDep,
    user: CurrentUser,
    x_access_token: Annotated[str | None, Header()] = None,
) -> list[AccessLinkOut]:
    rows = await app_access.list_for(session, user.id)
    current_hash = app_access.hash_token(x_access_token) if x_access_token else None
    return [
        _out(link, current=bool(current_hash and link.token_hash == current_hash)) for link in rows
    ]


@router.post("", response_model=AccessLinkCreated, status_code=status.HTTP_201_CREATED)
async def create_link(
    body: AccessLinkIn,
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
    _only: TelegramOnly,
) -> AccessLinkCreated:
    url_base = settings.mini_app_url
    if not url_base:
        # Пустой `MINI_APP_URL` — ошибка конфигурации, а не человека. Отдаём
        # понятный код, чтобы приложение не показывало битую ссылку.
        raise HTTPException(status.HTTP_409_CONFLICT, detail="mini_app_url_missing")
    link, token = await app_access.issue(
        session, user=user, mini_app_url=url_base, label=body.label
    )
    return AccessLinkCreated(
        id=link.id,
        url=app_access.build_url(url_base, token),
        expires_at=link.expires_at,
    )


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_link(
    link_id: int,
    session: SessionDep,
    user: CurrentUser,
    _only: TelegramOnly,
) -> Response:
    if not await app_access.revoke(session, user_id=user.id, link_id=link_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="link_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
