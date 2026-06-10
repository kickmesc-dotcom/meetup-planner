from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Any

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from app.bot.handlers import (
    admin_chukhan,
    bot_reactions,
    chat_capture,
    chat_commands,
    help as help_handler,
    media_reactions,
    next_meeting,
    poll_answer,
    start,
    whoami,
    zaebal,
)
from app.config import get_settings

log = logging.getLogger(__name__)

_bot: Bot | None = None
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


def _make_direct_connector() -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(
        family=socket.AF_INET,
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


def _proxy_pool_snapshot() -> list[Any]:
    """Вспомогательная функция — снимок пула из ProxyManager (для retry-логики)."""
    from app.services.proxies import _state
    return list(_state.pool)


def _build_session() -> AiohttpSession | None:
    """Return a session that forces IPv4, or None to use aiogram default.

    aiogram 3.13 хранит `timeout` в BaseSession.timeout и передаёт его как есть
    в `aiohttp.ClientSession.post(timeout=...)` (make_request). aiohttp 3.10
    принимает там как число, так и `ClientTimeout`-объект — поэтому даём
    гранулярный таймаут (GHG8 Q-NET.b): `total` < 30с (даём send успеть, но
    не виснем дольше), `sock_connect` ловит «коннект не встаёт». Per-request
    `request_timeout=N` (set_my_commands/set_webhook) по-прежнему перекрывает
    его числом — это ок, отдельные короткие вызовы.
    """
    if not _env_truthy("BOT_FORCE_IPV4", True):
        return None
    total, sock_connect = _resolve_timeouts()
    timeout = aiohttp.ClientTimeout(total=total, sock_connect=sock_connect)
    return _IPv4AiohttpSession(timeout=timeout)


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        settings = get_settings()
        token = settings.bot_token

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

        _bot = Bot(**kwargs)
    return _bot


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
        _dispatcher.include_router(start.router)
        _dispatcher.include_router(whoami.router)
        _dispatcher.include_router(poll_answer.router)
        _dispatcher.include_router(admin_chukhan.router)
        _dispatcher.include_router(next_meeting.router)
        # GHG6 K: /help до chat_capture catch-all — Command-фильтр всё равно
        # сработает первым, но порядок read-friendly.
        _dispatcher.include_router(help_handler.router)
        _dispatcher.include_router(chat_commands.router)
        # GHG6 E11: zaebal-команды — до catch-all chat_capture, иначе их «съест»
        # сохранение текста (Command-фильтры всё равно сработают первыми, но
        # для читаемости держим порядок).
        _dispatcher.include_router(zaebal.router)
        # GHG6 E9 / GHG7 P0.3.c: реакции бота — ДО chat_capture. Порядок
        # роутеров ВАЖЕН: bot_reactions матчит `F.text` и в aiogram остановил
        # бы пропагацию, поэтому on_message обязан завершаться `raise
        # SkipHandler`, чтобы chat_capture ниже по цепочке всё же сохранил
        # сообщение (см. bot_reactions.on_message).
        _dispatcher.include_router(bot_reactions.router)
        # GHG7 P5: медиа-реакции. Матчат контент-типы (photo/video/...), НЕ
        # F.text, поэтому с bot_reactions/chat_capture не конфликтуют. on_media
        # всё равно завершается raise SkipHandler (пропагация). Содержит и
        # @message_reaction-роутер (приём живых реакций для wait_then_chance).
        _dispatcher.include_router(media_reactions.router)
        _dispatcher.include_router(chat_capture.router)
    return _dispatcher
