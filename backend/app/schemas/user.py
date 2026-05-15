from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_id: int
    display_name: str
    username: str | None = None
    avatar_url: str | None = None
    color_hex: str
    timezone: str
    created_at: datetime
    is_admin: bool = False
