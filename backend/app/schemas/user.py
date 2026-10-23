from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # None — аккаунт заведён по почте (B2B_PLATFORM_PLAN, шаг 2.1).
    telegram_id: int | None = None
    email: str | None = None
    # Подтверждён ли адрес (шаг 2.1). False у аккаунта, заведённого по почте,
    # пока человек не открыл ссылку из письма.
    email_verified: bool = False
    display_name: str
    username: str | None = None
    avatar_url: str | None = None
    color_hex: str
    timezone: str
    created_at: datetime
    is_admin: bool = False
