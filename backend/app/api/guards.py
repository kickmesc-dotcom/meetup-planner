"""Предохранители периметра: размер тела, частота запросов, заголовки ответа.

Зачем модуль вообще
-------------------
Аудит 26.10.2026 (`docs/AUDIT_SECURITY_STABILITY.md`, находки S-2, S-3) показал
три вещи, которые не закрывались ни правами, ни проверкой подписи:

* **Тело запроса ничем не ограничено.** Ручки принимают `multipart/form-data`,
  а правило «до 8 МБ» в `hr_media.store_upload` срабатывает уже ПОСЛЕ того, как
  тело целиком принято и разложено python-multipart. Один запрос на несколько
  гигабайт заполнял временный диск контейнера — это отказ в обслуживании, а не
  «ошибка одного пользователя».
* **Публичные ручки входа не имели лимита частоты.** `POST /api/auth/login`
  перебирается без задержки, а `password/reset/request` на каждый вызов шлёт
  письмо — то есть чужими адресами можно было рассылать письма за наш счёт.
* **Ответы не несли защитных заголовков** (`X-Content-Type-Options`), из-за чего
  браузер мог «додумать» тип содержимого.

Почему middleware, а не проверка в ручках: размер тела и частоту нужно знать ДО
того, как ручка начнёт читать тело или ходить в базу. В ручке это уже поздно.

Про ограничение частоты честно: счётчики живут в памяти процесса. Реплика API
одна (Amvera — боевой контур, HF — стенд), поэтому это ровно то поведение,
которого мы ждём. При нескольких репликах лимит станет «на реплику» — для
перебора пароля это всё равно снимает скорость на порядок, а переносить счётчики
в базу стоит только вместе с реальным горизонтальным масштабированием.

Отдельно: у нас нет единого источника «адрес посетителя». HF и Amvera ставят
запрос за свой прокси, и адрес соединения там — внутренний. Поэтому ключ берётся
так: если адрес соединения публичный — это и есть посетитель; если приватный
(значит, мы за прокси) — берём первый хоп `X-Forwarded-For`. Заголовку можно
соврать, поэтому у каждого правила есть ещё общий счётчик на весь контур: он
ограничивает суммарный поток независимо от того, как часто меняют поддельный
адрес.
"""

from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Размер тела запроса
# ---------------------------------------------------------------------------

# 12 МБ: самое крупное тело у нас — фото до 8 МБ плюс multipart-обвязка, то есть
# запас в 1,5 раза. Больше не нужно ни одной ручке, включая вебхук Telegram.
DEFAULT_MAX_BODY_BYTES = 12 * 1024 * 1024
# `MAX_REQUEST_BYTES=0` (или `off`) выключает предохранитель — нужно для
# нагрузочных проб, где большой поток это цель, а не атака.
_OFF_VALUES = {"0", "off", "no", "false", "disabled"}


def max_body_bytes() -> int:
    """Предел тела запроса в байтах. `0` — предохранитель выключен."""
    raw = os.getenv("MAX_REQUEST_BYTES")
    if raw is None:
        return DEFAULT_MAX_BODY_BYTES
    if raw.strip().lower() in _OFF_VALUES:
        return 0
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_BODY_BYTES
    return max(0, value)


def _json_bytes(payload: dict[str, str]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class BodySizeLimitMiddleware:
    """Отклонять слишком большие тела до их обработки.

    Две проверки, потому что одной мало:

    1. `Content-Length` — дешёвый и точный отказ, если длина объявлена (так
       браузер и грузит фото);
    2. подсчёт байтов в потоке — на случай `Transfer-Encoding: chunked`, где
       длины нет вовсе, а тело может быть бесконечным. Как только суммарный
       размер превышает предел, мы прекращаем чтение (отдаём приложению
       усечённое тело и признак «конец»), а ответ приложения **подменяем** на
       `413` в момент его начала.

    Почему подмена, а не исключение в `receive`. Первая версия бросала
    `BodyTooLarge` из обёртки `receive` — и на живом запросе это давало `500`, а
    не `413`: `ServerErrorMiddleware` внутри приложения ловит любое исключение
    и сам формирует ответ, так что наружу исключение уже не выходило. Подмена
    ответа работает независимо от того, как приложение отреагировало на
    усечённое тело.

    Если ответ уже начал уходить (стриминг), статус менять поздно — тогда
    просто пишем в лог: тело всё равно не будет прочитано дальше предела.
    """

    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self._max_bytes = max_bytes

    @property
    def max_bytes(self) -> int:
        return self._max_bytes if self._max_bytes is not None else max_body_bytes()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.max_bytes
        if limit <= 0:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        declared = headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await self._reject(send)
                    return
            except ValueError:
                # Кривая длина — не повод пускать тело целиком: считаем в потоке.
                pass

        received = 0
        overflowed = False
        replaced = False

        async def capped_receive() -> Message:
            """Отдать приложению тело, оборвав его на превышении предела."""
            nonlocal received, overflowed
            message = await receive()
            if message["type"] != "http.request" or overflowed:
                return message
            body = message.get("body", b"")
            received += len(body)
            if received <= limit:
                return message
            overflowed = True
            log.warning(
                "guard.body_too_large",
                path=scope.get("path"),
                limit_bytes=limit,
                received_bytes=received,
            )
            # Говорим приложению «тело кончилось»: дальше читать нечего и незачем.
            return {"type": "http.request", "body": body, "more_body": False}

        async def watching_send(message: Message) -> None:
            nonlocal replaced
            if replaced:
                # Ответ уже подменён на 413 — чужие куски наружу не идём.
                return
            if message["type"] == "http.response.start" and overflowed:
                replaced = True
                await self._reject(send)
                return
            await send(message)

        await self.app(scope, capped_receive, watching_send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = _json_bytes({"detail": "body_too_large"})
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# Частота запросов
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateRule:
    """Правило частоты: `limit` запросов за `window` секунд на одного посетителя.

    `global_limit` — предел на весь контур за то же окно. Нужен из-за
    `X-Forwarded-For`: подделывая адрес, лимит на посетителя обходится, а общий
    счётчик — нет.
    """

    name: str
    methods: tuple[str, ...]
    pattern: re.Pattern[str]
    limit: int
    window: float
    global_limit: int

    def matches(self, method: str, path: str) -> bool:
        return method in self.methods and self.pattern.fullmatch(path) is not None


def _rule(
    name: str,
    methods: tuple[str, ...],
    pattern: str,
    limit: int,
    window: float,
    global_limit: int | None = None,
) -> RateRule:
    return RateRule(
        name=name,
        methods=methods,
        pattern=re.compile(pattern),
        limit=limit,
        window=window,
        # По умолчанию общий предел в 12 раз выше: контур из одного ресторана
        # столько не набирает, а перебор с подменой адреса упирается в него.
        global_limit=global_limit if global_limit is not None else limit * 12,
    )


def default_rules() -> list[RateRule]:
    """Правила по умолчанию.

    Лимиты выбраны «по человеку», а не «по безопасности вообще»: сотрудник,
    который ошибся паролем три раза и перезапросил письмо, не должен упираться
    в ограничение. Упирается тот, кто перебирает.
    """
    return [
        # Вход и регистрация: 20 попыток за 5 минут. Пароль в 8 символов этим не
        # подобрать, а скрипт «1000 попыток в секунду» не пройдёт.
        _rule(
            "auth_login",
            ("POST",),
            r"/api/auth/(login|register|password/reset/confirm|email/verify/confirm)",
            20,
            300.0,
        ),
        # Письма: 5 за 15 минут. Каждое письмо — деньги владельца и репутация
        # домена, поэтому здесь лимит жёстче, чем на вход.
        _rule(
            "auth_mail",
            ("POST",),
            r"/api/auth/(password/reset/request|email/verify/request)",
            5,
            900.0,
        ),
        # Загрузка фото: 60 за 5 минут — смена целиком, включая чек-лист с фото
        # на каждом пункте, укладывается с запасом.
        _rule("media_upload", ("POST",), r"/api/media", 60, 300.0),
        # Приглашения и вступление по коду: код организации — это пароль, значит
        # перебор надо замедлить так же, как у входа.
        _rule("org_join", ("POST",), r"/api/org/join", 10, 600.0),
        # Принятие приглашения и выпуск новых ссылок.
        _rule("invites", ("POST",), r"/api/invitations/[^/]+/(accept|decline)", 20, 600.0),
        # Обращения в поддержку/проблемы из приложения — чтобы журнал не залили.
        _rule("issues", ("POST",), r"/api/issues", 30, 600.0),
    ]


class SlidingWindowLimiter:
    """Скользящее окно по ключу. Чистая логика без сети и БД — тестируется как есть."""

    def __init__(self, max_keys: int = 20000) -> None:
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._max_keys = max_keys

    def check(
        self,
        key: str,
        *,
        limit: int,
        window: float,
        now: float | None = None,
    ) -> float | None:
        """`None` — запрос можно пускать; иначе — сколько секунд ждать."""
        moment = time.monotonic() if now is None else now
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        else:
            self._hits.move_to_end(key)
        edge = moment - window
        while hits and hits[0] <= edge:
            hits.popleft()
        if len(hits) >= limit:
            # Ждать — до выхода самого старого попадания из окна.
            return max(0.0, hits[0] + window - moment)
        hits.append(moment)
        # Память под контролем: пустые очереди и лишние ключи не копятся.
        while len(self._hits) > self._max_keys:
            self._hits.popitem(last=False)
        return None

    def clear(self) -> None:
        self._hits.clear()


_LIMITER = SlidingWindowLimiter()
_RULES: list[RateRule] | None = None


def rules() -> list[RateRule]:
    global _RULES
    if _RULES is None:
        _RULES = default_rules()
    return _RULES


def rate_limit_disabled() -> bool:
    return (os.getenv("RATE_LIMIT_OFF") or "").strip().lower() in {"1", "true", "yes", "on"}


def reset_rate_limits() -> None:
    """Забыть счётчики. Тесты и диагностика: состояние живёт в процессе."""
    _LIMITER.clear()


def _is_public_ip(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local)


def client_ip(scope: Scope) -> str:
    """Адрес посетителя для ключа лимита.

    Если адрес соединения публичный — это и есть посетитель (прямое
    подключение). Если приватный — мы за прокси, и настоящий адрес приходит
    в `X-Forwarded-For`; берём первый хоп (ближайший к клиенту) и полагаемся на
    общий счётчик правила, чтобы подделка заголовка не снимала лимит целиком.
    """
    client = (scope.get("client") or ("", 0))[0] or ""
    if client and _is_public_ip(client):
        return client
    forwarded = Headers(scope=scope).get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first[:64]
    return client or "unknown"


class RateLimitMiddleware:
    """Лимит частоты по правилам: `429` с `Retry-After` и понятным кодом."""

    def __init__(self, app: ASGIApp, rules_: list[RateRule] | None = None) -> None:
        self.app = app
        self._rules = rules_

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or rate_limit_disabled():
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "")
        # Предпросмотр CORS и HEAD не считаем: это не работа с данными, и
        # браузер шлёт их сам.
        if method in {"OPTIONS", "HEAD"}:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        active = self._rules if self._rules is not None else rules()
        for rule in active:
            if not rule.matches(method, path):
                continue
            ip = client_ip(scope)
            wait = _LIMITER.check(
                f"{rule.name}:{ip}", limit=rule.limit, window=rule.window
            )
            if wait is None:
                wait = _LIMITER.check(
                    f"{rule.name}:*", limit=rule.global_limit, window=rule.window
                )
            if wait is not None:
                seconds = max(1, math.ceil(wait))
                log.warning(
                    "guard.rate_limited",
                    rule=rule.name,
                    path=path,
                    client=ip,
                    retry_after=seconds,
                )
                body = _json_bytes({"detail": f"rate_limited:{seconds}"})
                await send(
                    {
                        "type": "http.response.start",
                        "status": 429,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                            (b"retry-after", str(seconds).encode()),
                            (b"cache-control", b"no-store"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            break
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Заголовки ответа
# ---------------------------------------------------------------------------

# Заголовки, которые уместны у любого ответа API и не зависят от ручки.
# `X-Content-Type-Options: nosniff` запрещает браузеру «угадывать» тип: без него
# ответ, отданный как `text/plain`, может быть исполнен как HTML.
# `Referrer-Policy` не даёт увести адрес с подписью (`?s=…`) на чужой сайт в
# заголовке перехода.
SAFE_RESPONSE_HEADERS: tuple[tuple[str, str], ...] = (
    ("x-content-type-options", "nosniff"),
    ("referrer-policy", "no-referrer"),
)


class SecurityHeadersMiddleware:
    """Дописать защитные заголовки, не перетирая то, что поставила ручка.

    `setdefault`, а не `update`: у медиа свой `Cache-Control`, у CORS свои
    заголовки, и затирать их из middleware нельзя.
    """

    def __init__(self, app: ASGIApp, headers: tuple[tuple[str, str], ...] = SAFE_RESPONSE_HEADERS) -> None:
        self.app = app
        self._headers = headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def add_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self._headers:
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, add_headers)
