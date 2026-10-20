"""Материалы смены из Google Sheets: забираем CSV и держим снимок в БД.

Почему не встроить таблицу iframe'ом или не открывать ссылку: у сотрудников в
России Google Sheets часто не открывается (или открывается без VPN, а иногда
и с ним). Сервер стоит вне этого контура, поэтому:

1. раз в несколько минут забирает CSV по `export?format=csv&gid=...`;
2. хранит последний удачный снимок в `sheet_sources.rows_json`;
3. приложение показывает снимок из своей БД — без единого запроса к Google.

Ошибка обновления НЕ затирает старые данные: в интерфейсе остаётся последняя
рабочая версия с пометкой «данные от …». Для графика смен это важнее свежести:
пустая таблица в смену хуже, чем вчерашняя.

Если таблица закрыта настройками доступа, Google отдаёт HTML страницы входа.
Это распознаётся по `text/html` и сохраняется как понятная ошибка, а не как
«таблица из одной ячейки».
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import SheetSource
from app.services import hr_access

log = structlog.get_logger()

SHEET_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
GID_RE = re.compile(r"(?:[?#&]gid=)(\d+)")
TIMEOUT_SECONDS = 20.0
STALE_MINUTES = 15
# График смен широкий: даты идут колонками, 24 колонки обрезали бы месяц.
MAX_ROWS = 600
MAX_COLS = 40

# Один общий замок: параллельные открытия экрана не должны запускать пять
# одинаковых запросов к Google.
_LOCK = asyncio.Lock()


class MaterialsError(Exception):
    """Отказ с кодом для API."""


@dataclass(frozen=True)
class Rows:
    rows: list[list[str]]
    columns: int


def parse_sheet(value: str) -> tuple[str, str | None]:
    """Достать id таблицы и gid из любой формы ссылки Google Sheets."""
    match = SHEET_RE.search(value or "")
    if match is None:
        raise MaterialsError("bad_sheet_url")
    gid_match = GID_RE.search(value or "")
    return match.group(1), (gid_match.group(1) if gid_match else None)


def export_url(spreadsheet_id: str, gid: str | None) -> str:
    suffix = f"&gid={gid}" if gid else ""
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        f"/export?format=csv{suffix}"
    )


def gviz_url(spreadsheet_id: str, gid: str | None) -> str:
    suffix = f"&gid={gid}" if gid else ""
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        f"/gviz/tq?tqx=out:csv{suffix}"
    )


def parse_csv(text: str) -> Rows:
    """CSV → прямоугольная таблица. Пустые хвосты отбрасываем."""
    reader = csv.reader(io.StringIO(text))
    rows: list[list[str]] = []
    for index, row in enumerate(reader):
        if index >= MAX_ROWS:
            break
        cells = [cell.strip() for cell in row[:MAX_COLS]]
        while cells and not cells[-1]:
            cells.pop()
        if not cells:
            continue
        rows.append(cells)
    width = max((len(row) for row in rows), default=0)
    for row in rows:
        row.extend([""] * (width - len(row)))
    return Rows(rows=rows, columns=width)


async def fetch_rows(spreadsheet_id: str, gid: str | None) -> Rows:
    """Скачать CSV. Экспорт → gviz как запасной путь (разные настройки доступа)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; SemiTaskBot/1.0; +https://github.com/)"
        ),
        "Accept": "text/csv,text/plain,*/*",
    }
    last_error: str | None = None
    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS, follow_redirects=True, headers=headers
    ) as client:
        for url in (export_url(spreadsheet_id, gid), gviz_url(spreadsheet_id, gid)):
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                last_error = f"network:{type(exc).__name__}"
                continue
            if response.status_code != 200:
                last_error = f"http_{response.status_code}"
                continue
            content_type = response.headers.get("content-type", "")
            if "text/html" in content_type:
                # Страница входа Google: таблица не опубликована.
                last_error = "access_denied"
                continue
            text = response.content.decode("utf-8-sig", errors="replace")
            if "<html" in text[:200].lower():
                last_error = "access_denied"
                continue
            return parse_csv(text)
    raise MaterialsError(last_error or "fetch_failed")


async def refresh(session: AsyncSession, source: SheetSource) -> SheetSource:
    """Обновить один источник. Ошибка сохраняется, но данные не теряются."""
    try:
        rows = await fetch_rows(source.spreadsheet_id, source.gid)
    except MaterialsError as exc:
        source.sync_error = str(exc)
        source.synced_at = source.synced_at or datetime.now(UTC)
        await session.commit()
        log.info("materials.refresh_failed", source=source.title, reason=str(exc))
        return source
    source.rows_json = json.dumps(rows.rows, ensure_ascii=False)
    source.synced_at = datetime.now(UTC)
    source.sync_error = None
    await session.commit()
    return source


def is_stale(source: SheetSource, *, now: datetime | None = None) -> bool:
    if source.synced_at is None:
        return True
    moment = now or datetime.now(UTC)
    synced = source.synced_at
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=UTC)
    return moment - synced > timedelta(minutes=STALE_MINUTES)


def decode_rows(source: SheetSource) -> list[list[str]]:
    if not source.rows_json:
        return []
    try:
        data = json.loads(source.rows_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        [str(cell) if cell is not None else "" for cell in row]
        for row in data
        if isinstance(row, list)
    ]


async def visible_sources(
    session: AsyncSession, employee
) -> list[SheetSource]:  # noqa: ANN001 - Employee без публичного протокола
    stmt = (
        select(SheetSource)
        .where(SheetSource.is_active.is_(True))
        .order_by(SheetSource.sort_order, SheetSource.id)
    )
    rows = list((await session.scalars(stmt)).all())
    if hr_access.is_admin(employee):
        return rows
    return [
        source
        for source in rows
        if source.department_id is None
        or source.department_id == employee.department_id
    ]


async def refresh_stale(session: AsyncSession, sources: list[SheetSource]) -> None:
    """Тихо обновить устаревшие источники.

    Замок без ожидания: если обновление уже идёт (другой запрос), просто
    отдаём то, что есть в БД — экран не должен ждать чужой сети.
    """
    if not any(is_stale(source) for source in sources):
        return
    if _LOCK.locked():
        return
    async with _LOCK:
        for source in sources:
            if is_stale(source):
                await refresh(session, source)
                await session.refresh(source)


async def refresh_one(session: AsyncSession, source_id: int) -> SheetSource:
    source = await session.get(SheetSource, source_id)
    if source is None:
        raise MaterialsError("source_not_found")
    return await refresh(session, source)
