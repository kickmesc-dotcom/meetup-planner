from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.config import get_settings
from app.db.models import User
from app.schemas.user import UserOut
from app.services.admin_config import (
    get_ui_hide_greeting,
    get_ui_welcome_format,
    set_ui_hide_greeting,
    set_ui_welcome_format,
)

router = APIRouter(tags=["users"])


def _avatar_display_url(u: User) -> str | None:
    """URL аватарки для ОТОБРАЖЕНИЯ в мини-аппе (НЕ для чухан-постинга).

    Приоритет: ручная ссылка (Серж/Митян — приватность TG) → стабильный прокси
    /api/avatar/{id} → None (фронт рисует инициалы). Прямой `u.avatar_url` сюда
    НЕ отдаём: его file_path протухает за ~1ч → «приложуха забывает аватарки»
    (прод-фидбек 18.06 #2). Прокси-URL резолвит свежий file_path по стабильному
    file_id на лету. `?v=` — cache-buster: меняется вместе с file_id (т.е. когда
    юзер реально сменил аватар), иначе браузер показывал бы старую картинку по
    неизменному URL.
    """
    if u.avatar_manual_url:
        return u.avatar_manual_url
    if u.avatar_file_id:
        base = get_settings().public_base_url.rstrip("/")
        ver = u.avatar_file_id[-12:]
        return f"{base}/api/avatar/{u.id}?v={ver}"
    return None


def _to_out(u: User, *, admin_ids: set[int]) -> UserOut:
    return UserOut(
        id=u.id,
        telegram_id=u.telegram_id,
        display_name=u.display_name,
        username=u.username,
        avatar_url=_avatar_display_url(u),
        color_hex=u.color_hex,
        timezone=u.timezone,
        created_at=u.created_at,
        is_admin=u.telegram_id in admin_ids,
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    admin_ids = get_settings().admin_tg_id_set
    return _to_out(user, admin_ids=admin_ids)


@router.get("/users", response_model=list[UserOut])
async def list_users(session: SessionDep, _: CurrentUser) -> list[UserOut]:
    admin_ids = get_settings().admin_tg_id_set
    result = await session.scalars(select(User).order_by(User.id))
    return [_to_out(u, admin_ids=admin_ids) for u in result.all()]


# --- GHG8 (18.06 #2): прокси аватарок ---
# Стабильный URL для <img> в мини-аппе. ПУБЛИЧНЫЙ (без tma-auth): тег <img> не
# умеет слать Authorization-заголовок. Утечки нет — отдаём только публичную
# аватарку по числовому id, токен бота наружу не идёт (проксируем байты сами,
# не редиректим на file-URL с токеном). file_path резолвится по стабильному
# file_id и кешируется в памяти (≤ раз в 50 мин на участника) — узкий канал к TG
# почти не трогаем. Чинит «приложуха забывает аватарки» (раньше в БД хранился
# протухающий за ~1ч file-URL).
@router.get("/avatar/{user_id}")
async def avatar_proxy(user_id: int, session: SessionDep, response: Response):
    from app.bot.dispatcher import get_bot
    from app.services.avatars import fetch_avatar_bytes

    u = await session.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    # Ручная ссылка обслуживается напрямую фронтом (она и так стабильна) —
    # сюда участник с ручной картинкой и без TG-фото попасть не должен, но на
    # всякий случай отвечаем 404, чтобы не маскировать ошибку конфигурации.
    if not u.avatar_file_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no_avatar")

    data = await fetch_avatar_bytes(get_bot(), u.avatar_file_id)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "avatar_unavailable")
    payload, content_type = data
    response.headers["Content-Type"] = content_type
    # Кешируем на сутки; смена аватара меняет file_id → меняется ?v= в URL →
    # браузер запросит заново (cache-bust на стороне URL, см. _avatar_display_url).
    response.headers["Cache-Control"] = "public, max-age=86400"
    return Response(
        content=payload,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# --- E7: per-user UI prefs (закрываемое приветствие) ---
# GHG8 P4: + welcome_format (name|avatar|both, P4.1.b — один селектор на все
# welcome-блоки). В PUT оба поля опциональны — клиенты шлют только то, что
# меняют (старый фронт слал {hide_greeting} без формата — совместимо).


class UiPrefsOut(BaseModel):
    hide_greeting: bool
    welcome_format: str  # name | avatar | both


class UiPrefsPatch(BaseModel):
    hide_greeting: bool | None = None
    welcome_format: str | None = Field(
        None, pattern="^(name|avatar|both)$"
    )


@router.get("/me/ui-prefs", response_model=UiPrefsOut)
async def get_ui_prefs(session: SessionDep, user: CurrentUser) -> UiPrefsOut:
    return UiPrefsOut(
        hide_greeting=await get_ui_hide_greeting(session, user.telegram_id),
        welcome_format=await get_ui_welcome_format(session, user.telegram_id),
    )


@router.put("/me/ui-prefs", response_model=UiPrefsOut)
async def put_ui_prefs(
    body: UiPrefsPatch, session: SessionDep, user: CurrentUser
) -> UiPrefsOut:
    if body.hide_greeting is not None:
        await set_ui_hide_greeting(session, user.telegram_id, body.hide_greeting)
    if body.welcome_format is not None:
        await set_ui_welcome_format(
            session, user.telegram_id, body.welcome_format
        )
    return UiPrefsOut(
        hide_greeting=await get_ui_hide_greeting(session, user.telegram_id),
        welcome_format=await get_ui_welcome_format(session, user.telegram_id),
    )
