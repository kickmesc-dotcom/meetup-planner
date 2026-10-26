"""Приём апдейтов Telegram: чужой вебхук-секрет — 403, наш апдейт — принят.

Почему ответ ограничен по времени (26.10.2026)
----------------------------------------------
Жалоба владельца: `/changelog` «залипает» — ответ не приходит вовсе, а иногда
приходит через час или шесть. Дело не в самой истории изменений и не в кнопке,
а в том, как вебхук отвечает Telegram.

Telegram ждёт ответ на вебхук **60 секунд**; не дождавшись, считает доставку
неуспешной и **повторяет тот же апдейт позже** («give up after a reasonable
amount of attempts» в документации Bot API). Отсюда оба симптома сразу:

* апдейт мы всё-таки обработали, ответ ушёл — но Telegram не знает об этом и
  шлёт апдейт заново; второй проход печатает вторую копию ответа через час или
  шесть. Это и есть «приходит спустя 6 часов»;
* если и повтор не укладывается в окно, Telegram перестаёт повторять совсем —
  и человек не получает ничего.

Замер до правки: у `/changelog` было четыре уровня доставки по три попытки с
таймаутом 12 с — **до 154 секунд** на один апдейт, в 2,5 раза больше окна
Telegram. Причина была не только в команде: вебхук ждал обработчик целиком,
поэтому медленным мог оказаться любой сценарий (фото, шаблон, импорт).

Как теперь
----------
1. Апдейт принимается в работу отдельной задачей, а ответ Telegram уходит
   сразу после `WEBHOOK_RESPONSE_BUDGET_SECONDS` — независимо от того,
   закончил ли обработчик. Это ровно то, что aiogram делает в
   `feed_webhook_update`; здесь это сделано явно, чтобы рядом жили дедупликация
   и понятный лог.
2. Быстрый апдейт (99% случаев) по-прежнему отрабатывается целиком до ответа:
   ждать бюджет на каждое нажатие кнопки незачем — задача уже готова, и
   `asyncio.wait` возвращается сразу.
3. Повторная доставка того же `update_id` не обрабатывается дважды: иначе
   поздний повтор Telegram печатал бы вторую копию уже отправленного ответа.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict
from typing import Annotated, Any

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

# Сколько секунд вебхук готов ждать обработчик, прежде чем ответить Telegram и
# оставить задачу доделывать работу в фоне. Меньше окна Telegram (60 с) — с
# двукратным запасом, чтобы ответ дошёл даже при медленном канале.
DEFAULT_RESPONSE_BUDGET_SECONDS = 30.0
# Границы, в которые можно загнать бюджет через env. Снизу — чтобы случайное
# «0.001» не отправило в фон вообще все апдейты (тогда любая остановка контейнера
# теряет работу, о которой Telegram уже сказали «ок»). Сверху — 55 с: дальше
# Telegram всё равно перестаёт ждать ответ и повторяет апдейт.
MIN_RESPONSE_BUDGET_SECONDS = 3.0
MAX_RESPONSE_BUDGET_SECONDS = 55.0


def response_budget_seconds() -> float:
    """Бюджет ответа вебхука. Задан с запасом и настраивается через env."""
    raw = os.getenv("WEBHOOK_RESPONSE_BUDGET_SECONDS")
    if not raw:
        return DEFAULT_RESPONSE_BUDGET_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_RESPONSE_BUDGET_SECONDS
    return max(
        MIN_RESPONSE_BUDGET_SECONDS, min(MAX_RESPONSE_BUDGET_SECONDS, value)
    )


# --- Задачи, доделывающие апдейт после ответа Telegram ----------------------
# Держим сильные ссылки: собранная сборщиком мусора задача молча перестала бы
# выполняться, и апдейт пропал бы совсем.
_TASKS: set[asyncio.Task[None]] = set()

# --- Дедупликация повторной доставки ---------------------------------------
# Telegram повторяет апдейт, если не получил ответ; повторы приходят в пределах
# часов, а не секунд, поэтому запоминаем `update_id` на 6 часов. Память — 4096
# последних апдейтов: столько их и бывает за такой срок у одного бота. Хранить
# это в базе незачем: там на счету каждая запись (Neon), а после рестарта
# контейнера повтор уже ничего не портит — ответ мог уйти только до рестарта.
SEEN_UPDATE_TTL_SECONDS = 6 * 3600.0
SEEN_UPDATE_MAX = 4096

_seen_updates: OrderedDict[int, float] = OrderedDict()


def remember_update(update_id: int | None, *, now: float | None = None) -> bool:
    """Запомнить апдейт. `True` — такой уже видели (повтор доставки).

    `None` в `update_id` невозможен у Telegram, но модель `Update` его
    допускает; неизвестный id не дедуплицируем — лучше обработать дважды, чем
    выбросить настоящий апдейт.
    """
    if update_id is None:
        return False
    moment = time.monotonic() if now is None else now
    while _seen_updates:
        oldest_id, oldest_at = next(iter(_seen_updates.items()))
        if moment - oldest_at <= SEEN_UPDATE_TTL_SECONDS and len(_seen_updates) <= SEEN_UPDATE_MAX:
            break
        _seen_updates.pop(oldest_id, None)
    if update_id in _seen_updates:
        # Освежаем запись: повтор пришёл — значит апдейт ещё «горячий».
        _seen_updates.move_to_end(update_id)
        _seen_updates[update_id] = moment
        return True
    _seen_updates[update_id] = moment
    return False


def reset_seen_updates() -> None:
    """Забыть историю апдейтов (тесты, диагностика)."""
    _seen_updates.clear()


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


async def wait_pending_tasks(timeout: float = 10.0) -> int:
    """Дождаться апдейтов, которые доделываются после ответа Telegram.

    Без этого шага на остановке контейнера (деплой, перезапуск) апдейт, за
    который мы уже отчитались `ok`, терялся бы на середине: Telegram повторять
    его не станет — ответ-то был успешный. Возвращает, сколько задач осталось
    незавершёнными (они будут отменены вместе с процессом).
    """
    pending = [task for task in _TASKS if not task.done()]
    if not pending:
        return 0
    log.info("webhook.draining_updates", count=len(pending), timeout_sec=timeout)
    done, still_running = await asyncio.wait(pending, timeout=timeout)
    for task in still_running:
        task.cancel()
    return len(still_running)


async def _feed(dp: Any, bot: Any, update: Update, org_id: int) -> None:
    """Обработать апдейт, не бросая исключение наружу.

    Раньше ошибка обработчика гасилась здесь же (`webhook.handler_error`) и
    вебхук всё равно отвечал `ok` — Telegram в таком случае апдейт не повторяет,
    и это правильно: повтор ничего не изменит. Поведение сохранено, но теперь
    функция живёт в отдельной задаче, поэтому ловим исключение внутри.
    """
    try:
        await dp.feed_update(bot, update)
    except Exception:  # noqa: BLE001 — сеть/БД/TG: логируем, ответ уже ушёл
        log.exception(
            "webhook.handler_error", update_id=update.update_id, org_id=org_id
        )


def _detach(task: asyncio.Task[None], *, update_id: int | None, org_id: int) -> None:
    """Убрать задачу из набора и записать, что она доделалась после ответа.

    Без этой строки в логе не отличить «ответ ушёл, работа продолжается» от
    «работа вообще потерялась». Коллбэк несёт и вторую обязанность: выбрасывает
    задачу из `_TASKS`, иначе набор рос бы без предела.
    """

    def _done(finished: asyncio.Task[None]) -> None:
        _TASKS.discard(finished)
        if not finished.cancelled():
            log.info("webhook.slow_update_done", update_id=update_id, org_id=org_id)

    task.add_done_callback(_done)


async def _process(dp: Any, bot: Any, update: Update, org_id: int) -> bool:
    """Запустить обработку и подождать её не дольше бюджета.

    `True` — обработчик успел закончить, вебхук ответил «после факта».
    `False` — обработчик продолжает работать в фоне, а Telegram уже получил
    ответ (иначе он повторил бы доставку и человек увидел бы вторую копию).

    Отдельная задача, а не `wait_for`, потому что `wait_for` по истечении
    времени ОТМЕНЯЕТ работу. Отменять середину сценария нельзя: половина
    поручения уже записана, а сообщение ещё нет.
    """
    task = asyncio.create_task(_feed(dp, bot, update, org_id))
    _TASKS.add(task)
    budget = response_budget_seconds()
    started = time.monotonic()
    done, _pending = await asyncio.wait({task}, timeout=budget)
    if task in done:
        _TASKS.discard(task)
        return True
    log.warning(
        "webhook.slow_update",
        update_id=update.update_id,
        org_id=org_id,
        budget_sec=budget,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
    _detach(task, update_id=update.update_id, org_id=org_id)
    return False


@router.post("/tg/webhook")
async def tg_webhook(
    request: Request,
    session: SessionDep,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    org_id = await resolve_org(session, x_telegram_bot_api_secret_token)

    payload = await request.json()
    update = Update.model_validate(payload)
    if remember_update(update.update_id):
        # Повтор доставки: ответ на этот апдейт уже отправлялся (или
        # отправляется прямо сейчас). Вторая копия — это тот самый «ответ через
        # шесть часов», поэтому повтор пропускаем, но отвечаем `ok`.
        log.info(
            "webhook.duplicate_update", update_id=update.update_id, org_id=org_id
        )
        return {"ok": True}
    dp = get_dispatcher()
    bot = bot_for_org(org_id)
    # Весь обработчик видит только данные этой организации: фильтр запросов
    # берёт организацию из контекста (app/db/tenancy.py). Отдельная задача
    # наследует контекст на момент создания, поэтому `reset_org` ниже ей не
    # мешает.
    token = set_org(org_id)
    try:
        await _process(dp, bot, update, org_id)
    finally:
        reset_org(token)
    return {"ok": True}
