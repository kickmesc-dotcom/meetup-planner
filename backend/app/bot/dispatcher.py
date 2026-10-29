from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from typing import Any

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.client.telegram import TelegramAPIServer

from app.bot.handlers import (
    app_link,
    changelog,
    help as help_handler,
    hr_alerts,
    hr_bot,
    next_meeting,
    poll_answer,
    whoami,
)
from app.config import get_settings

log = logging.getLogger(__name__)

# Боты по организациям (B2B_PLATFORM_PLAN, шаг 1.6). Ключ — `org_id`, а не
# токен: токен может смениться (клиент пересоздал бота), и старый Bot остался
# бы висеть вместе со своим пулом соединений. Диспетчер один: он не хранит
# состояние конкретного бота, бот приходит аргументом в `feed_update`.
_bots: dict[int, Bot] = {}
_dispatcher: Dispatcher | None = None


def _env_truthy(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# GHG8 Q-NET.b: параметры пула/таймаутов коннектора. Лечат корень «зависает,
# рестарт расклинивает»: при РКН-throttling полудохлое keep-alive-соединение
# оставалось в пуле и переиспользовалось → каждый следующий запрос виснул на
# нём до плоских 30с. keepalive_timeout режет такие соединения, гранулярный
# ClientTimeout фейлит быстрее, BOT_FORCE_CLOSE — аварийный «вообще без пула».
def _resolve_keepalive_timeout() -> float:
    return float(_env_int("BOT_KEEPALIVE_TIMEOUT", 15))


def _resolve_force_close() -> bool:
    return _env_truthy("BOT_FORCE_CLOSE", False)


def _resolve_timeouts() -> tuple[float, float]:
    """(total, sock_connect) в секундах. total < 30с сессии — даём send успеть,
    но не виснем дольше; sock_connect ловит «коннект не устанавливается»."""
    return float(_env_int("BOT_TOTAL_TIMEOUT", 25)), float(
        _env_int("BOT_SOCK_CONNECT_TIMEOUT", 8)
    )


def _pool_connector_kwargs() -> dict[str, Any]:
    """Общие kwargs пула для direct- и proxy-коннектора.

    aiohttp запрещает keepalive_timeout вместе с force_close=True
    (ValueError), поэтому при force_close keepalive не передаём.
    """
    if _resolve_force_close():
        return {"force_close": True}
    return {"keepalive_timeout": _resolve_keepalive_timeout()}


def _connector_family() -> int:
    """Какое семейство адресов разрешаем для Bot API.

    Раньше здесь жёстко стоял `AF_INET`: у HF Spaces тогда не было рабочего
    IPv6, и запросы через IPv6 висли. 24.10.2026 выяснилось, что стало
    наоборот: `api.telegram.org` и `workers.dev` **не доходят через IPv4**
    (пин на `AF_INET` давал таймаут на каждой отправке, 190 с на апдейт),
    а тот же контейнер спокойно тянул `https://api.github.com` через
    `httpx` — тот семейство не пиннит. Поэтому семейство теперь следует
    за `BOT_FORCE_IPV4` (дефолт — оба), а не задаётся молча.
    """
    return socket.AF_INET if _env_truthy("BOT_FORCE_IPV4", True) else socket.AF_UNSPEC


def _make_direct_connector() -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(
        family=_connector_family(),
        ssl=True,
        ttl_dns_cache=300,
        limit=20,
        enable_cleanup_closed=True,
        **_pool_connector_kwargs(),
    )


def _make_proxy_connector(rec: Any) -> aiohttp.BaseConnector | None:
    """SOCKS5/HTTP-прокси через aiohttp_socks. MTProto-прокси не подходят
    для HTTP Bot API — для них возвращаем None и пропускаем.

    GHG8 Q-NET.b: те же keepalive/force_close, что у direct — это свойство
    пула, не направление (выбор прокси/первый зелёный прокси не трогаем, Q8).
    ProxyConnector наследует TCPConnector и принимает эти kwargs.
    """
    proxy_type = (rec.type or "").lower()
    if proxy_type not in {"socks5", "http"}:
        return None
    try:
        from aiohttp_socks import ProxyConnector, ProxyType
    except ImportError:
        log.warning("proxy.aiohttp_socks_missing")
        return None
    pt = ProxyType.SOCKS5 if proxy_type == "socks5" else ProxyType.HTTP
    return ProxyConnector(
        proxy_type=pt,
        host=rec.server,
        port=rec.port,
        password=rec.secret if proxy_type == "socks5" else None,
        rdns=True,
        **_pool_connector_kwargs(),
    )


class _IPv4AiohttpSession(AiohttpSession):
    """aiogram session с двумя фичами:

    1. IPv4-пин (HF Spaces часто не маршрутизирует IPv6).
    2. Smart-proxy fallback (P2): при `AUTO_FALLBACK`/`ALWAYS_ON` после
       сетевой ошибки запрос ретраится через ближайший живой прокси
       из пула (`app.services.proxies`). Лимит — 3 попытки на запрос,
       минимум 5 с между переключениями (по всем запросам).

    MTProto-прокси сохраняются в пуле, но для HTTP Bot API не годятся —
    используются только SOCKS5/HTTP. Парсер MTProto-каналов из GHG5
    отложен в P3 — наполнение пула ручное / через `PROXIES_BOOTSTRAP_JSON`.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._active_proxy_id: int | None = None  # None = direct

    async def _build_session(
        self, proxy_rec: Any | None
    ) -> aiohttp.ClientSession:
        if proxy_rec is None:
            connector = _make_direct_connector()
        else:
            connector = _make_proxy_connector(proxy_rec) or _make_direct_connector()
        return aiohttp.ClientSession(connector=connector, trust_env=True)

    async def _swap_session(self, proxy_rec: Any | None) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = await self._build_session(proxy_rec)
        self._active_proxy_id = proxy_rec.id if proxy_rec is not None else None

    async def create_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = await self._build_session(None)
            self._active_proxy_id = None
        return self._session

    async def make_request(self, *args: Any, **kwargs: Any) -> Any:
        """Запрос в Bot API с резервным ПУТЁМ доступа, а не только с повтором.

        Если задан `BOT_API_SERVER` (Cloudflare-воркер-реверс-прокси), то
        именно он и только он был единственным адресом Bot API. 24.10.2026
        выяснилось, чем это кончается: из контейнера этот путь перестал
        отвечать (30 с таймаута на каждый запрос, `TelegramNetworkError`), и
        бот замолчал целиком — не только `/changelog`. При этом прямой
        `api.telegram.org` отвечал с другой машины за 1–2 с.

        Поэтому после всех повторов через прокси-пул делаем ОДНУ попытку
        напрямую, короткую (8 с): она не должна растягивать вебхук-окно
        Telegram. Ушло — логируем, что спас обходной путь.
        """
        method = _method_name(args, kwargs)
        started = time.monotonic()
        try:
            result = await self._make_request_with_pool(*args, **kwargs)
        except Exception as exc:
            # `extra=`, а не именованные поля: здесь `log` — обычный логгер из
            # `logging`. Если передать `method=…` напрямую, stdlib бросит
            # `TypeError: Logger._log() got an unexpected keyword argument`,
            # и настоящая ошибка сети подменится ошибкой логирования — именно
            # так родился лог «webhook.set_failed: Logger._log() ...».
            log.warning(
                "telegram.request_failed",
                extra={
                    "method": method,
                    "error": exc.__class__.__name__,
                    "detail": str(exc)[:160],
                    "host": _api_host(self.api),
                    "family": _family_label(),
                    "ms": int((time.monotonic() - started) * 1000),
                },
            )
            if _is_default_api(self.api):
                # Уже ходили напрямую — второй такой же попытки не нужно.
                raise
            return await self._make_request_direct_fallback(exc, *args, **kwargs)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        # Медленный, но успешный запрос — это тот же симптом, что и таймаут,
        # только на шаг раньше. Пишем его громко, а штатные — шёпотом: иначе
        # лог бота тонет в `getMe`.
        slow = elapsed_ms >= SLOW_REQUEST_MS
        getattr(log, "warning" if slow else "debug")(
            "telegram.request_slow" if slow else "telegram.request_ok",
            extra={
                "method": method,
                "host": _api_host(self.api),
                "family": _family_label(),
                "ms": elapsed_ms,
            },
        )
        return result

    async def _make_request_direct_fallback(
        self, exc: Exception, *args: Any, **kwargs: Any
    ) -> Any:
        """Одна попытка мимо `BOT_API_SERVER` — прямо на api.telegram.org."""
        fallback = AiohttpSession(timeout=self.timeout)
        try:
            result = await asyncio.wait_for(
                fallback.make_request(*args, **kwargs), timeout=DIRECT_FALLBACK_SECONDS
            )
        except Exception:  # noqa: BLE001 — отдаём исходную ошибку, она информативнее
            log.warning(
                "telegram.direct_fallback_failed",
                extra={"error": exc.__class__.__name__},
            )
            raise exc from None
        finally:
            await fallback.close()
        log.warning(
            "telegram.direct_fallback_ok", extra={"error": exc.__class__.__name__}
        )
        return result

    async def _make_request_with_pool(self, *args: Any, **kwargs: Any) -> Any:
        # Импорт здесь — чтобы цикла импорта не было (proxies → db → ...).
        from app.db.base import get_sessionmaker
        from app.services.proxies import (
            MAX_ATTEMPTS_PER_REQUEST,
            ProxyMode,
            can_switch,
            ensure_loaded,
            get_state_snapshot,
            mark_proxy_failed,
            mark_proxy_ok,
            mark_switch,
            pick_next_alive,
        )

        # Если прокси-режим выключен глобально env-флагом, идём direct.
        if not _env_truthy("SMART_PROXY_ENABLED", True):
            return await super().make_request(*args, **kwargs)

        sm = get_sessionmaker()
        async with sm() as db:
            await ensure_loaded(db)
        state = get_state_snapshot()
        mode = ProxyMode(state["mode"])

        # ALWAYS_OFF — direct, без ретраев через прокси.
        if mode is ProxyMode.ALWAYS_OFF:
            return await super().make_request(*args, **kwargs)

        # ALWAYS_ON — сразу строим сессию через прокси, если её нет.
        if mode is ProxyMode.ALWAYS_ON and self._active_proxy_id is None:
            rec = pick_next_alive()
            if rec is not None and can_switch():
                mark_switch()
                await self._swap_session(rec)

        last_exc: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS_PER_REQUEST + 1):
            try:
                result = await super().make_request(*args, **kwargs)
                # Успех — отметим прокси как живой.
                if self._active_proxy_id is not None:
                    async with sm() as db:
                        cur_rec = next(
                            (
                                r
                                for r in _proxy_pool_snapshot()
                                if r.id == self._active_proxy_id
                            ),
                            None,
                        )
                        if cur_rec is not None:
                            await mark_proxy_ok(db, cur_rec)
                return result
            except (
                aiohttp.ClientConnectorError,
                aiohttp.ClientOSError,
                aiohttp.ServerDisconnectedError,
                asyncio.TimeoutError,
            ) as exc:
                last_exc = exc
                log.warning(
                    "proxy.request_failed",
                    extra={
                        "attempt": attempt,
                        "active_proxy_id": self._active_proxy_id,
                        "exc": exc.__class__.__name__,
                    },
                )
                # Если был активный прокси — помечаем мёртвым.
                if self._active_proxy_id is not None:
                    async with sm() as db:
                        cur_rec = next(
                            (
                                r
                                for r in _proxy_pool_snapshot()
                                if r.id == self._active_proxy_id
                            ),
                            None,
                        )
                        if cur_rec is not None:
                            await mark_proxy_failed(db, cur_rec)
                if attempt >= MAX_ATTEMPTS_PER_REQUEST:
                    break
                if not can_switch():
                    # Слишком быстро переключаемся — отдадим текущий исход.
                    break
                # Подбираем следующий путь.
                if mode is ProxyMode.AUTO_FALLBACK:
                    next_rec = pick_next_alive()
                    if next_rec is None:
                        # Прокси кончились — пробуем direct, если ещё не пробовали.
                        if self._active_proxy_id is None:
                            break
                        mark_switch()
                        await self._swap_session(None)
                    else:
                        mark_switch()
                        await self._swap_session(next_rec)
                elif mode is ProxyMode.ALWAYS_ON:
                    next_rec = pick_next_alive()
                    if next_rec is None:
                        break
                    mark_switch()
                    await self._swap_session(next_rec)
        assert last_exc is not None
        # GHG6 PX9: пишем хвост последней ошибки — чтобы UI его показал.
        try:
            from app.db.base import get_sessionmaker as _gsm2
            from app.services.proxies import record_last_error as _rec_err

            sm2 = _gsm2()
            async with sm2() as _db:
                await _rec_err(
                    _db,
                    message=f"{last_exc.__class__.__name__}: {last_exc}",
                    mode_used=mode.value,
                    proxy_id=self._active_proxy_id,
                )
        except Exception:  # noqa: BLE001
            # Не глушим оригинальную ошибку из-за проблемы записи диагностики.
            log.exception("proxy.record_last_error_failed")
        raise last_exc


# С какого времени запрос к Telegram считается «медленным» (для логов).
SLOW_REQUEST_MS = 2000

# Сколько ждём единственную попытку мимо `BOT_API_SERVER`. Коротко: второй
# такой же таймаут не должен съедать окно вебхука (60 с).
DIRECT_FALLBACK_SECONDS = 8.0


def _family_label() -> str:
    """Что в логе: ходим только по IPv4 или по обоим семействам."""
    return "ipv4" if _connector_family() == socket.AF_INET else "any"


def _api_host(api: Any) -> str:
    """Куда именно идёт запрос — воркер или сам Telegram (для логов)."""
    base = str(getattr(api, "base", "") or "")
    if not base:
        return "api.telegram.org"
    return base.split("//")[-1].split("/")[0]


def _method_name(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Имя метода Bot API (`sendMessage`, `getMe`, …) — для логов без шума."""
    method = args[1] if len(args) > 1 else kwargs.get("method")
    return str(getattr(method, "__api_method__", "")) or "unknown"


def _is_default_api(api: Any) -> bool:
    """Это api.telegram.org (или ничего не задано)? Тогда обходной путь — тот же
    адрес, и пробовать его второй раз бессмысленно."""
    base = str(getattr(api, "base", "") or "")
    return not base or base.startswith("https://api.telegram.org")


def _proxy_pool_snapshot() -> list[Any]:
    """Вспомогательная функция — снимок пула из ProxyManager (для retry-логики)."""
    from app.services.proxies import _state
    return list(_state.pool)


def _resolve_api_server() -> TelegramAPIServer | None:
    """BOT_API_SERVER (опц.): базовый URL Bot API. Пусто = напрямую на
    api.telegram.org (дефолт aiogram). Если HF режет прямой egress в TG
    (РКН-блокировка), задаём URL cloudflare-воркера-реверс-прокси (worker
    переписывает host → api.telegram.org), напр.
    https://telegram-proxy.kickmesc.workers.dev

    ВАЖНО: кастомный сервер в aiogram 3.x задаётся ТОЛЬКО на сессии
    (`BaseSession(api=...)`). `Bot(server=...)` молча уходит в **kwargs и
    игнорируется — поэтому api пробрасываем в `_IPv4AiohttpSession`.
    """
    raw = (os.getenv("BOT_API_SERVER") or "").strip()
    if not raw:
        return None
    return TelegramAPIServer.from_base(raw)


def _build_session() -> AiohttpSession | None:
    """Return a session that forces IPv4 / custom API server, or None.

    aiogram 3.13 хранит `timeout` в BaseSession.timeout и передаёт его как есть
    в `aiohttp.ClientSession.post(timeout=...)` (make_request). Плоский total
    (HOTFIX 2026-06-12: Q-NET.b sock_connect=8 рубил TLS-handshake под
    РКН-throttling из HF → бот слеп; вернули поведение до f629fa0). Per-request
    `request_timeout=N` (set_my_commands/set_webhook) перекрывает его числом.

    Кастомный `api` (BOT_API_SERVER) задаётся здесь, на сессии — это
    единственное рабочее место (Bot(server=...) игнорируется в aiogram 3.x).
    """
    api = _resolve_api_server()
    # `BOT_FORCE_IPV4=false` раньше отключало только сам класс сессии, а
    # коннектор всё равно оставался IPv4 — то есть флаг не работал там, где он
    # нужен (при заданном `BOT_API_SERVER`). Теперь семейство адресов берётся
    # из `_connector_family()`, а сессия нужна всегда, если есть api.
    if api is None and not _env_truthy("BOT_FORCE_IPV4", True):
        return None
    total = float(_env_int("BOT_TOTAL_TIMEOUT", 30))
    kwargs: dict = {"timeout": total}
    if api is not None:
        kwargs["api"] = api
    return _IPv4AiohttpSession(**kwargs)


def _build_bot(token: str) -> Bot:
    """Новый aiogram-бот с нашим IPv4/прокси-слоем."""
    # Token may be SecretStr in future config; keep the guard.
    if hasattr(token, "get_secret_value"):
        token = token.get_secret_value()
    session = _build_session()
    kwargs: dict = {
        "token": str(token),
        "default": DefaultBotProperties(parse_mode=ParseMode.HTML),
    }
    if session is not None:
        kwargs["session"] = session
    return Bot(**kwargs)


def get_bot() -> Bot:
    """Бот ТЕКУЩЕЙ организации.

    Чей бот вернуть, решает контекст (`current_org_id`): вебхук ставит его по
    секрету, API — по сотруднику, планировщик живёт в организации по
    умолчанию. Организация без своего токена работает на env-боте, поэтому
    текущий контур ничего не замечает.
    """
    from app.db.org_models import current_org_id
    from app.services import org_bots

    org_id = current_org_id.get()
    bot = _bots.get(org_id)
    if bot is None:
        token = org_bots.token_for(org_id) or get_settings().bot_token
        bot = _build_bot(str(token))
        _bots[org_id] = bot
    return bot


def bot_for_org(org_id: int) -> Bot:
    """Бот конкретной организации (вебхук уже знает, чей апдейт пришёл)."""
    from app.services import org_bots

    bot = _bots.get(org_id)
    if bot is None:
        token = org_bots.token_for(org_id) or get_settings().bot_token
        bot = _build_bot(str(token))
        _bots[org_id] = bot
    return bot


def all_bots() -> list[Bot]:
    return list(_bots.values())


def reset_bots() -> None:
    """Забыть ботов (тесты, смена токена). Сессии закрывает вызывающий."""
    _bots.clear()


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
        # SemiTaskBot: активны только роутеры рабочего контура. Шуточные
        # хендлеры (чухан, лох, мемы, музыка, пауза бота, ранги) перенесены в
        # `app/_legacy/bot/handlers` и здесь НЕ подключаются — см. докапакет
        # `app/_legacy`. Наследный `start.py` («кнопка Планера») тоже не
        # подключён: его сценарий заменён онбордингом сотрудника.
        _dispatcher.include_router(hr_bot.router)
        # Кнопки под алертами руководителя («решено», «напомнить завтра», мьют).
        # Свой префикс `hra:` — с кнопками сценария сотрудника (`hr:`) не спорит.
        _dispatcher.include_router(hr_alerts.router)
        _dispatcher.include_router(whoami.router)
        # `/app` — вход в широкую веб-версию с компьютера (ссылка доступа).
        _dispatcher.include_router(app_link.router)
        _dispatcher.include_router(changelog.router)
        _dispatcher.include_router(poll_answer.router)
        _dispatcher.include_router(next_meeting.router)
        _dispatcher.include_router(help_handler.router)
        # Кнопки из СТАРЫХ сообщений (прежние сборки меню): ловушка обязана
        # стоять последней, иначе заберёт чужие callback_data. Без неё нажатие
        # на устаревшее меню не давало ничего — см. `hr_bot.on_stale_callback`.
        _dispatcher.include_router(hr_bot.stale_router)
    return _dispatcher
