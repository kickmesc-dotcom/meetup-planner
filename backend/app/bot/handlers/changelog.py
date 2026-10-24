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

from app.services.changelog import (
    Changelog,
    build_changelog,
    build_view,
    render_changelog,
)

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


async def _send(
    message: Message, text: str, *, plain: bool, as_reply: bool
) -> None:
    """Один вариант отправки: ответом на сообщение или просто в чат.

    `as_reply=False` — не запасной «на всякий случай», а отдельный путь.
    `message.reply` требует права отвечать на конкретное сообщение: в группе с
    ограничениями и в канале это `BadRequest`, хотя обычная отправка в тот же
    чат разрешена. Раньше все попытки шли только через `reply`, и такая
    ошибка выглядела как «бот молчит».
    """
    kwargs = {
        # `None` (а не `Default`) — у бота разметка включена по умолчанию;
        # здесь она не нужна, и `<` в заголовке не сломает отправку.
        "parse_mode": None if plain else "HTML",
        "disable_web_page_preview": True,
    }
    if as_reply:
        await message.reply(text, **kwargs)
    else:
        await message.answer(text, **kwargs)


async def _deliver(
    message: Message, text: str, *, plain: bool = False, as_reply: bool = True
) -> bool:
    """Отправка с повторами. `False` — доставить не удалось (уже залогировано).

    Таймаут держим `asyncio.wait_for`, а не `request_timeout=` у сообщения.
    24.10.2026: `Message.reply(..., request_timeout=12)` выглядел как лимит, но
    в aiogram 3.x этот аргумент уходит в поля `SendMessage` и на сетевой
    таймаут не влияет — запрос жил по таймауту сессии (30–60 с). Из-за этого
    одна попытка занимала минуту, три попытки не влезали в окно вебхука
    Telegram, и апдейт обрабатывался по 190 с. `wait_for` рвёт попытку ровно
    через `REPLY_TIMEOUT_SECONDS`, что бы ни происходило внутри.

    `as_reply=False` — обычная отправка в чат. Нужна как отдельный запасной
    путь: если чат запрещает ответы на сообщения, `reply` отваливается с
    `BadRequest`, хотя отправка в тот же чат разрешена.
    """
    for attempt in range(1, REPLY_ATTEMPTS + 1):
        try:
            await asyncio.wait_for(
                _send(message, text, plain=plain, as_reply=as_reply),
                timeout=REPLY_TIMEOUT_SECONDS,
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
            # Это не сеть: «can't parse entities», «message is too long»,
            # «not enough rights to reply» и прочее. Повтор того же текста
            # бессмысленен — сразу даём шанс короткой версии без разметки.
            log.warning(
                "changelog.reply_rejected",
                attempt=attempt,
                error=exc.__class__.__name__,
                detail=str(exc)[:200],
            )
            return False
    return False


# Сколько ждём GitHub, прежде чем показать историю без него. Ручные записи
# лежат в коде и не требуют сети, поэтому «показать хоть что-то» возможно
# всегда. Ждать 6 секунд ради свежих коммитов, которые всё равно не факт что
# попадут в первые строки, — плохой размен: вебхук-окно у Telegram конечно.
GITHUB_BUDGET_SECONDS = 1.5

SILENCE_FALLBACK = (
    "🧩 Что нового\n\n"
    "История изменений сейчас недоступна. Загляни в неё на GitHub: "
    "команда /changelog работает, но сервис истории не ответил. "
    "Попробуй ещё раз через минуту."
)


@router.message(Command("changelog"))
async def on_changelog(message: Message) -> None:
    """`/changelog` отвечает ВСЕГДА — пусть иногда коротко.

    Три уровня: полная история (HTML) → три заголовка без разметки → короткая
    строка. Раньше любой сбой любого уровня оставлял человека без ответа; для
    этого и нужен последний уровень, даже если он и выглядит беднее.
    """
    log.info(
        "changelog.command",
        chat_type=getattr(message.chat, "type", None),
        message_id=getattr(message, "message_id", None),
    )
    view = None
    try:
        view = await asyncio.wait_for(
            build_changelog(), timeout=GITHUB_BUDGET_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 — история не повод молчать
        # Истёк бюджет GitHub — это штатно, а не поломка. Всё остальное тоже
        # не повод молчать: ниже показываем историю без сети.
        log.warning("changelog.build_failed", error=exc.__class__.__name__)
        try:
            view = build_view([], source_ok=False)
        except Exception:  # noqa: BLE001
            view = None

    if view is not None:
        text = render_changelog(view)[:MAX_MESSAGE_CHARS]
        if await _deliver(message, text):
            return
        # Полный ответ не прошёл — пробуем короткий и без разметки: и
        # ответом, и обычной отправкой (чат мог запретить reply).
        short = render_short_fallback(view)
        if await _deliver(message, short, plain=True):
            return
        if await _deliver(message, short, plain=True, as_reply=False):
            return

    # Последний уровень не зависит ни от сети, ни от разметки, ни от разбора
    # истории: если не ушло и это, в логах будет `changelog.reply_lost`, а не
    # тишина без следа.
    if await _deliver(message, SILENCE_FALLBACK, plain=True, as_reply=False):
        return
    log.error("changelog.reply_lost", entries=len(view.entries) if view else 0)
