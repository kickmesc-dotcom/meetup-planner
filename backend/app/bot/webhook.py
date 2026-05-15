from __future__ import annotations

from typing import Annotated

import structlog
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.bot.dispatcher import get_bot, get_dispatcher
from app.config import get_settings

log = structlog.get_logger()
router = APIRouter()


@router.post("/tg/webhook")
async def tg_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    settings = get_settings()
    if x_telegram_bot_api_secret_token != settings.tg_webhook_secret:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bad_secret")

    payload = await request.json()
    update = Update.model_validate(payload)
    dp = get_dispatcher()
    bot = get_bot()
    try:
        await dp.feed_update(bot, update)
    except Exception:  # noqa: BLE001
        log.exception("webhook.handler_error", update_id=update.update_id)
    return {"ok": True}
