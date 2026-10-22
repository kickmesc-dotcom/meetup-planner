from __future__ import annotations

from typing import Annotated

import structlog
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.api.deps import SessionDep
from app.bot.dispatcher import bot_for_org, get_dispatcher
from app.config import get_settings
from app.db.org_models import DEFAULT_ORG_ID, reset_org, set_org
from app.services import org_bots

log = structlog.get_logger()
router = APIRouter()


async def resolve_org(session: SessionDep, secret: str | None) -> int:
    """Чья это организация по секрету вебхука (B2B_PLATFORM_PLAN, шаг 1.6).

    Секрет — единственное, чему можно верить до разбора апдейта: он приходит в
    заголовке от Telegram, а тело подписано ботом, которого мы ещё не знаем.
    Неизвестный секрет — 403, а не «обслужим ботом по умолчанию»: иначе
    достаточно прислать любой апдейт, чтобы он обработался от чужого имени.

    Реестр обновляем, если секрет не нашёлся: организация могла только что
    получить своего бота, и первый апдейт не должен потеряться.
    """
    settings = get_settings()
    await org_bots.ensure_loaded(session)
    found = org_bots.org_for_webhook_secret(secret or "")
    if found is None:
        await org_bots.reload(session)
        found = org_bots.org_for_webhook_secret(secret or "")
    if found is None and secret and secret == settings.tg_webhook_secret:
        # Реестр может быть ещё пуст (например, в тестах): контур по умолчанию
        # обслуживается env-секретом.
        found = DEFAULT_ORG_ID
    if found is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bad_secret")
    return found


@router.post("/tg/webhook")
async def tg_webhook(
    request: Request,
    session: SessionDep,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    org_id = await resolve_org(session, x_telegram_bot_api_secret_token)

    payload = await request.json()
    update = Update.model_validate(payload)
    dp = get_dispatcher()
    bot = bot_for_org(org_id)
    # Весь обработчик видит только данные этой организации: фильтр запросов
    # берёт организацию из контекста (app/db/tenancy.py).
    token = set_org(org_id)
    try:
        await dp.feed_update(bot, update)
    except Exception:  # noqa: BLE001
        log.exception(
            "webhook.handler_error", update_id=update.update_id, org_id=org_id
        )
    finally:
        reset_org(token)
    return {"ok": True}
