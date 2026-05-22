from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.config import get_settings
from app.db.models import User
from app.schemas.user import UserOut
from app.services.admin_config import (
    get_ui_hide_greeting,
    set_ui_hide_greeting,
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


class UiPrefsIO(BaseModel):
    hide_greeting: bool


@router.get("/me/ui-prefs", response_model=UiPrefsIO)
async def get_ui_prefs(session: SessionDep, user: CurrentUser) -> UiPrefsIO:
    hide = await get_ui_hide_greeting(session, user.telegram_id)
    return UiPrefsIO(hide_greeting=hide)


@router.put("/me/ui-prefs", response_model=UiPrefsIO)
async def put_ui_prefs(
    body: UiPrefsIO, session: SessionDep, user: CurrentUser
) -> UiPrefsIO:
    await set_ui_hide_greeting(session, user.telegram_id, body.hide_greeting)
    return UiPrefsIO(hide_greeting=body.hide_greeting)
