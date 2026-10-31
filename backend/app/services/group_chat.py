"""Групповой чат — необязательный аксессуар бота.

Что изменилось в продукте. Раньше бот жил в рабочем чате: люди сидели в группе,
а приложение было надстройкой. Теперь наоборот — сотрудник заходит в мини-апп и
**сам выбирает команду**; группа остаётся полезной (анонсы, общий пул
работников, «кто в команде»), но её отсутствие не должно ломать ничего.

Отсюда правило этого модуля: чат может быть, может не быть, может умереть —
приложение работает одинаково. Конкретно:

* чата нет в конфиге (`GROUP_CHAT_ID` пуст) — просто нечего проверять;
* чат есть, но Telegram отвечает `chat not found` (бот выведен из группы или
  id устарел) — выключаем env-чат в реестре организаций. Дальше
  `settings.group_chat_id` честно возвращает `None`, и все места с
  `if not settings.group_chat_id` тихо пропускают свою групповую часть вместо
  повторяющихся ошибок Telegram;
* сеть/прокси подвели при проверке — НЕ выключаем: временный сбой не повод
  терять рабочий чат, проверка повторится на следующем старте.

Почему на старте, а не на каждом вызове. `getChat` — сетевой запрос, а
`settings.group_chat_id` читается десятки раз на запрос. Одна проверка на
будильник даёт тот же результат и стоит один вызов за запуск контейнера.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()

# Проверка идёт один раз за жизнь процесса: повторные вызовы (ретраи старта,
# второй вебхук) должны быть бесплатными.
_checked = False
_alive: bool | None = None

# По этим ответам Telegram чат признаётся мёртвым навсегда. Остальные ошибки
# (таймаут, 502, RKN-троттлинг) считаем временными.
_PERMANENT_MARKERS = (
    "chat not found",
    "chat_not_found",
    "bot was kicked",
    "bot is not a member",
    "group chat was upgraded",
    "chat_id is empty",
    "peer_id_invalid",
)


def _is_permanent(error: str) -> bool:
    low = (error or "").lower()
    return any(marker in low for marker in _PERMANENT_MARKERS)


def reset() -> None:
    """Забыть результат проверки (тесты и явная перепроверка)."""
    global _checked, _alive
    _checked = False
    _alive = None


def state() -> dict[str, object]:
    """Что известно о чате — для диагностики и тестов."""
    return {"checked": _checked, "alive": _alive}


async def validate_env_chat(bot=None) -> bool:
    """Проверить чат из `GROUP_CHAT_ID` и выключить его, если он мёртв.

    Возвращает `True`, если групповая часть доступна (или её не настраивали),
    и `False`, если чат выключен. Исключений не бросает: старт приложения не
    должен зависеть от состояния чужой группы.
    """
    global _checked, _alive

    from app.config import get_settings

    settings = get_settings()
    chat_id = getattr(settings, "group_chat_id_env", None)

    if _checked:
        return bool(_alive)

    if not chat_id:
        _checked = True
        _alive = False
        log.info("group_chat.not_configured")
        return False

    if bot is None:
        try:
            from app.bot.dispatcher import get_bot

            bot = get_bot()
        except Exception as exc:  # noqa: BLE001 — нет токена/сети: не наша вина
            log.warning("group_chat.no_bot", error=str(exc)[:160])
            return False

    try:
        await bot.get_chat(chat_id=chat_id, request_timeout=10)
    except Exception as exc:  # noqa: BLE001 — любой ответ Telegram это данные
        text = str(exc)
        if _is_permanent(text):
            from app.services import org_bots

            org_bots.disable_env_chat(text)
            _checked = True
            _alive = False
            log.warning(
                "group_chat.disabled",
                chat_id=chat_id,
                reason=text[:200],
                hint="бота могли вывести из группы или id устарел; "
                "приложение работает без чата",
            )
            return False
        # Временная ошибка: оставляем чат включённым и попробуем снова.
        log.warning("group_chat.probe_failed", chat_id=chat_id, error=text[:200])
        return True

    _checked = True
    _alive = True
    log.info("group_chat.ready", chat_id=chat_id)
    return True
