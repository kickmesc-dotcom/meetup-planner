from __future__ import annotations

from fastapi import APIRouter
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


def _to_out(u: User, *, admin_ids: set[int]) -> UserOut:
    return UserOut(
        id=u.id,
        telegram_id=u.telegram_id,
        display_name=u.display_name,
        username=u.username,
        avatar_url=u.avatar_url,
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
