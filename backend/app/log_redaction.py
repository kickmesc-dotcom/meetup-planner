"""Полоскание подписей в логах: подписанная ссылка не должна утечь в лог.

Зачем (аудит 26.10.2026, находка S-17). Часть наших адресов — это пропуск:
`/api/media/{id}?s=<подпись>` открывается без заголовков (иначе `<img>` не
работает), `/api/meetings/ical/{id}.ics?t=<подпись>` живёт вечно, а в
`TG_WEBHOOK_SECRET` вообще лежит ключ вебхука. И адреса, и тексты исключений
попадают в лог тривиально: `log.warning("media.fetch_failed", url=url)` или
`log.error(..., error=str(exc))`, где `str(exc)` из `httpx`/`aiohttp` печатает
полный URL запроса. Логи хостинга при этом доступны куда большему числу людей,
чем база: их читают в панели, они уезжают в вывод деплой-скриптов и в переписку.

Что делаем: перед записью проходим по значениям события и вырезаем хвосты
подписей. Ключ (`s`, `t`, `token`…) и адрес остаются — по ним видно, ЧТО
запрашивали, а сама подпись (то есть право на доступ) исчезает.

Почему не «убрать логирование URL»: диагностика подписанных ссылок — это ровно
то, ради чего лог и открывают (какой blob не отдался, какой хост ответил 404).
Полезно и безопасно одновременно получается только полосканием.

Границы честно: это защита от случайной утечки в лог, а не от целенаправленной
атаки. Значение, собранное из кусков (`s=` + `abc` + `def`), полоскание не
увидит, поэтому новый код по-прежнему не должен логировать подписи руками.
"""

from __future__ import annotations

import re
import sys
from typing import Any

import structlog

# Так помечаем вырезанное. Специально не `***`: видно, что это намеренно, а не
# случайный мусор в строке.
REDACTED = "<подпись-скрыта>"

# Хвост подписи после параметра. Ключи перечислены явно и покрывают все места,
# где мы вообще выдаём подписанный адрес: медиа (`s`), iCal (`t`), а также
# типовые имена из сторонних клиентов (`token`, `signature`, `secret`), которые
# попадают к нам в логи из чужих ошибок и вебхуков.
_QUERY_SIGNATURE = re.compile(
    r"(?P<prefix>[?&](?:s|t|sig|sign|signature|token|access_token|secret|key)=)"
    r"[^&\s\"'<>]*",
    re.IGNORECASE,
)
# Заголовок авторизации в тексте исключения или в дампе запроса.
_BEARER = re.compile(r"(?P<prefix>\bBearer\s+)[A-Za-z0-9._~+/-]{8,}=*", re.IGNORECASE)
# Секрет вебхука Telegram: он же пропуск к диагностике, он же ключ подписи iCal.
_WEBHOOK_SECRET = re.compile(
    r"(?P<prefix>X-Telegram-Bot-Api-Secret-Token[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+",
    re.IGNORECASE,
)
# Пароль в DSN: `postgresql://user:password@host` в тексте ошибки подключения.
_DSN_PASSWORD = re.compile(r"(?P<prefix>://[^:/@\s]+:)[^@/\s]+(?=@)")

# Пары «подстрока-признак → правило»: признак ищем поиском подстроки (это дёшево
# в CPython), и только если он есть — запускаем регулярку. Важно не перепутать:
# именно на этом в первой версии поломался лог с заголовком
# `X-Telegram-Bot-Api-Secret-Token: <секрет>` — в нём нет ни `=`, ни `://`,
# и общий дешёвый выход пропускал сам секрет.
_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("=", _QUERY_SIGNATURE),
    ("bearer", _BEARER),
    ("secret-token", _WEBHOOK_SECRET),
    ("://", _DSN_PASSWORD),
)


def scrub(text: str) -> str:
    """Вырезать подписи из строки. Всё остальное оставить как есть."""
    if not text:
        return text
    lowered = text.lower()
    result = text
    for marker, pattern in _SIGNALS:
        if marker in lowered:
            result = pattern.sub(lambda m: m.group("prefix") + REDACTED, result)
    return result


def scrub_value(value: Any) -> Any:
    """Полоскание значения любого типа: строки — целиком, остальное как есть."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {key: scrub_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(scrub_value(item) for item in value)
    return value


def redact_event(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Процессор `structlog`: полоскание всех строковых значений события.

    Ставится последним перед рендерером, чтобы не зависеть от того, добавит ли
    предыдущий процессор ещё одну строку с адресом (например, трейсбек).
    """
    for key in list(event_dict):
        event_dict[key] = scrub_value(event_dict[key])
    return event_dict


def configure_logging() -> None:
    """Единая настройка `structlog` для всех процессов контейнера.

    Зачем отдельная функция, а не `structlog.configure(processors=…)` на месте.
    Поток логов у нас **stderr**, а не stdout. Причина найдена 31.10.2026, когда
    выяснилось, что в панели Amvera за четыре часа нет ни одной записи structlog,
    хотя `apscheduler` и `uvicorn` пишут нормально: те идут через стандартный
    `logging`, чей дефолтный обработчик смотрит в stderr, а `PrintLogger`
    structlog по умолчанию смотрит в stdout — и его панель не собирает. Из-за
    этого `scheduler.job_fired`, `scheduler.job_failed` и прочая диагностика
    существовали только на бумаге: их не было видно там, где их ищут.

    `flush=True` внутри `PrintLogger.msg` означает, что дело не в буферизации —
    меняем именно приёмник. Второй заход по stdout (например, в CI) не нужен:
    stderr неотличимо виден в обоих случаях, потому что это тот же поток вывода
    контейнера.
    """
    structlog.configure(
        processors=log_processors(),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


def log_processors() -> list[Any]:
    """Цепочка процессоров `structlog` — одна на все процессы контейнера.

    Живёт здесь, а не в `app/main.py`, по важной причине: `app.db.migrate`
    стартует отдельным процессом перед uvicorn, и импорт ради одной функции
    из `main` поднял бы в нём всё приложение (FastAPI, все роутеры, aiogram).
    На тарифе в 0,5 ГБ каждый лишний мегабайт в этом процессе виден (см. S-19).
    """
    return [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        # Ближе к концу цепочки, но до рендерера: полоскаем уже собранные строки,
        # включая те, что добавили предыдущие процессоры (трейсбек, ошибку).
        redact_event,
        # Не JSON. Проверено на живом контейнере 31.10.2026: панель Amvera
        # показывает только строки без JSON-объектов — `{…}` в её ленте не
        # появляются вообще, а консольный `event key=value` виден нормально.
        # Поэтому здесь читаемый однострочный формат, а не JSONRenderer:
        # некрасивый лог, который видно, полезнее красивого, которого нет.
        # `colors=False` явно: в контейнере нет TTY, а управляющие
        # последовательности только мешают grep'у по логам.
        structlog.dev.ConsoleRenderer(colors=False),
    ]
