from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.initdata import InitDataError, parse_and_verify
from app.config import Settings, get_settings
from app.db.base import get_sessionmaker
from app.db.models import User


async def db_session() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _strip_tma_prefix(authorization: str) -> str:
    if authorization.lower().startswith("tma "):
        return authorization[4:].strip()
    return authorization.strip()


async def current_user(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing_authorization")

    init_data = _strip_tma_prefix(authorization)
    try:
        payload = parse_and_verify(
            init_data,
            settings.bot_token,
            max_age_seconds=settings.initdata_max_age_seconds,
        )
    except InitDataError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=f"initdata_invalid:{exc}") from exc

    user = await session.scalar(select(User).where(User.telegram_id == payload.user_id))
    if user is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="not_in_whitelist",
        )

    # Lazy-update username if Telegram changed it.
    if payload.username and payload.username != user.username:
        user.username = payload.username
        await session.commit()
        await session.refresh(user)

    return user


CurrentUser = Annotated[User, Depends(current_user)]
