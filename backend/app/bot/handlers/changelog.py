"""Чат-команда `/changelog`: что нового, обычными словами.

Почему не «вот список коммитов». Коммит пишется для разработчика: `fix(ui):
шапка и вкладки на узком экране` сотруднику ничего не говорит. Поэтому текст
сначала проходит адаптацию (редакторскую или автоматическую) и только потом
попадает в чат — см. `services/changelog.py`. Здесь только доставка.

Команда открыта всем, кто пишет боту: это история продукта, а не внутренняя
кухня. Сеть (GitHub) может быть недоступна — тогда сервис отдаёт то, что уже
описано вручную, и честно об этом пишет.

Почему доставка с повторами (24.10.2026). Владелец дважды написал `/changelog`
и не получил ничего. В логах — `webhook.handler_error`, апдейт «не обработан»
через 31.8 с: GitHub ответил за секунду, а отправка сообщения в Telegram
висела до таймаута. Один длинный ответ через прокси-слой оказался единственной
точкой отказа: не прошёл он — и человек не увидел даже «нет истории». Поэтому
теперь отправка повторяется, а последним шагом уходит короткая версия без
разметки: три заголовка и ссылка. Пусть лучше меньше текста, чем тишина.
"""

from __future__ import annotations

import asyncio

import structlog
from aiogram import Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.filters import Command
from aiogram.types import Message

from app.services.changelog import Changelog, build_changelog, render_changelog

log = structlog.get_logger()

router = Router()

# Телеграм-лимит — 4096 символов; держим запас, чтобы HTML-разметка не обрезала
# текст на середине тега.
MAX_MESSAGE_CHARS = 3800
# Сколько раз пробуем доставить полный ответ и сколько ждём одну попытку.
# 3 × 12 с + запас на GitHub (6 с) укладывается в вебхук-окно Telegram (60 с).
REPLY_ATTEMPTS = 3
REPLY_TIMEOUT_SECONDS = 12


def render_short_fallback(view: Changelog) -> str:
    """Короткая версия без разметки: три заголовка и ссылка.

    Запасной путь на случай, когда полный ответ не доставляется: маленькое
    сообщение проходит там, где большой HTML отваливается по таймауту.
    """
    titles = [item.title for item in view.entries[:3]]
    lines = ["🧩 Что нового:"] + [f"• {title}" for title in titles]
    if not titles:
        lines.append("Пока без изменений — только сели за работу.")
    lines.append(f"Полная история: {view.repo_url}")
    return "\n".join(lines)


async def _pause(seconds: float) -> None:
    """Пауза между попытками (отдельной функцией — чтобы тесты не ждали)."""
    await asyncio.sleep(seconds)


async def _deliver(message: Message, text: str, *, plain: bool = False) -> bool:
    """Отправка с повторами. `False` — доставить не удалось (уже залогировано)."""
    for attempt in range(1, REPLY_ATTEMPTS + 1):
        try:
            await message.reply(
                text,
                # `None` (а не `Default`) — у бота разметка включена по
                # умолчанию; здесь она не нужна, и `<` в заголовке не сломает
                # отправку.
                parse_mode=None if plain else "HTML",
                disable_web_page_preview=True,
                request_timeout=REPLY_TIMEOUT_SECONDS,
            )
            return True
        except TelegramRetryAfter as exc:
            # Telegram сам просит подождать — ждём ровно столько, сколько просят.
            log.warning(
                "changelog.reply_retry_after", attempt=attempt, seconds=exc.retry_after
            )
            await _pause(min(exc.retry_after, REPLY_TIMEOUT_SECONDS))
        except (TelegramNetworkError, TimeoutError) as exc:
            log.warning(
                "changelog.reply_network",
                attempt=attempt,
                error=exc.__class__.__name__,
            )
            await _pause(0.8 * attempt)
        except TelegramAPIError as exc:
            # Это не сеть: «can't parse entities», «message is too long» и
            # прочее. Повтор бессмысленен — сразу даём шанс короткой версии.
            log.warning(
                "changelog.reply_rejected",
                attempt=attempt,
                error=exc.__class__.__name__,
                detail=str(exc)[:200],
            )
            return False
    return False


@router.message(Command("changelog"))
async def on_changelog(message: Message) -> None:
    view = await build_changelog()
    text = render_changelog(view)[:MAX_MESSAGE_CHARS]
    if await _deliver(message, text):
        return
    # Полный ответ не прошёл — пробуем короткий и без разметки. Если и он не
    # уйдёт, человек всё равно ничего не получит, но тогда в логах будет
    # `changelog.reply_lost`, а не молчание без следа.
    if await _deliver(message, render_short_fallback(view), plain=True):
        return
    log.error("changelog.reply_lost", entries=len(view.entries))
