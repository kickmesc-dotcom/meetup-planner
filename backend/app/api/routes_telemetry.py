"""Приёмник ошибок фронта: одна ручка вместо «у клиента белый экран».

Зачем. До этого ошибка рендера оставалась в консоли браузера клиента, и
единственным сигналом было сообщение «ничего не работает». Здесь фронт
присылает уже очищенный отчёт: тип (падение рендера, ошибка окна, отклонённый
промис), текст, стек, путь и метку сборки.

Почему без авторизации. Ошибка случается и до входа — на форме, при разборе
ссылки, в офлайне. Требовать токен значило бы терять именно те падения,
которые чаще всего и ломают первый экран.

Почему сервер чистит путь сам. Фронт уже убирает query, но полагаться на
клиент нельзя: адрес с `?access=…` не должен попасть в логи даже при
сломанном/старом фронте. Стек и текст ограничены по длине — это не канал
для пересылки данных, а сигнал.
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, model_validator

from app.services import rum

router = APIRouter(tags=["telemetry"])
log = structlog.get_logger()

MAX_MESSAGE = 300
MAX_STACK = 4000
MAX_COMPONENT_STACK = 1500
MAX_PATH = 200
MAX_BUILD = 40
MAX_DEVICE = 20
MAX_PLATFORM = 20
MAX_CSP_FIELD = 300


def clean_path(path: str) -> str:
    """Путь без query/hash: подпись доступа и параметры в логи не уходят."""
    head = path.split("?", 1)[0].split("#", 1)[0]
    return head[:MAX_PATH]


class ClientErrorIn(BaseModel):
    """Отчёт фронта. Поля необязательные: лучше сигнал без деталей, чем 422."""

    kind: Literal["render", "error", "rejection"] = "error"
    message: str = Field("", max_length=MAX_MESSAGE)
    stack: str = Field("", max_length=MAX_STACK)
    component_stack: str = Field("", max_length=MAX_COMPONENT_STACK)
    path: str = Field("", max_length=MAX_PATH)
    build: str = Field("", max_length=MAX_BUILD)
    device: str = Field("", max_length=MAX_DEVICE)
    platform: str = Field("", max_length=MAX_PLATFORM)
    tg_version: str = Field("", max_length=MAX_PLATFORM)
    # Сколько раз повторилась та же ошибка: фронт схлопывает повторы, чтобы
    # цикл перерисовки не превратился в поток запросов.
    count: int = Field(1, ge=1, le=100)

    @model_validator(mode="after")
    def _require_signal(self) -> "ClientErrorIn":
        """Отчёт без текста и без стека — не сигнал, а шум в логах."""
        if not self.message.strip() and not self.stack.strip():
            raise ValueError("empty_report")
        return self


@router.post("/telemetry", status_code=204)
async def accept_client_error(payload: ClientErrorIn) -> Response:
    """Записать отчёт в лог. Ответ пустой: фронту нечего с ним делать."""
    log.warning(
        "client.error",
        kind=payload.kind,
        message=payload.message,
        path=clean_path(payload.path),
        build=payload.build,
        device=payload.device,
        platform=payload.platform,
        tg_version=payload.tg_version,
        count=payload.count,
        stack=payload.stack,
        component_stack=payload.component_stack,
    )
    return Response(status_code=204)


class VitalsIn(BaseModel):
    """Одно измерение Core Web Vitals с устройства.

    Список имён закрыт: всё остальное — мусор от старых сборок и ботов, и
    складывать его в сводку значило бы портить p75.
    """

    name: Literal["LCP", "INP", "CLS", "FCP", "TTFB"]
    value: float = Field(ge=0, le=600_000)
    rating: Literal["good", "needs-improvement", "poor"] | None = None
    device: str = Field("", max_length=MAX_DEVICE)
    platform: str = Field("", max_length=MAX_PLATFORM)
    path: str = Field("", max_length=MAX_PATH)
    build: str = Field("", max_length=MAX_BUILD)


@router.post("/telemetry/vitals", status_code=204)
async def accept_vitals(payload: VitalsIn) -> Response:
    """Принять метрику RUM. Ответ пустой: браузеру нечего с ним делать."""
    rum.rum.record(
        name=payload.name,
        value=payload.value,
        device=payload.device,
        path=clean_path(payload.path),
        build=payload.build,
    )
    return Response(status_code=204)


def _clip(value: object, limit: int = MAX_CSP_FIELD) -> str:
    return str(value or "")[:limit]


@router.post("/telemetry/csp", status_code=204)
async def accept_csp_report(request: Request) -> Response:
    """Нарушение CSP с браузера: какая директива и какой адрес заблокированы.

    Без авторизации: отчёт приходит со страницы, где сессии могло ещё не быть.
    Тело — `{"csp-report": {...}}` (report-uri) или массив (report-to).
    Любой мусор молча проглатываем: приёмник не должен превращаться в ошибку.
    """
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001 — невалидное тело не повод для 422
        return Response(status_code=204)

    report: dict = {}
    if isinstance(raw, dict):
        nested = raw.get("csp-report")
        report = nested if isinstance(nested, dict) else raw
    elif isinstance(raw, list) and raw and isinstance(raw[0], dict):
        body = raw[0].get("body")
        report = body if isinstance(body, dict) else raw[0]

    log.warning(
        "client.csp",
        directive=_clip(
            report.get("violated-directive") or report.get("effective-directive")
        ),
        blocked=_clip(report.get("blocked-uri")),
        document=clean_path(_clip(report.get("document-uri"), MAX_PATH)),
        disposition=_clip(report.get("disposition"), 20),
    )
    return Response(status_code=204)
