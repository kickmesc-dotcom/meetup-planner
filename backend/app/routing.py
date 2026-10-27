"""Перечисление маршрутов, не зависящее от раскладки `app.router.routes`.

Зачем отдельный модуль (аудит 26.10.2026, S-18). До Starlette 1.x включённые
роутеры разворачивались в плоский список: `app.routes` отдавал все 354 объекта,
и по нему можно было проверять «у каждой админ-ручки есть зависимость
авторизации». В Starlette 1.x `app.routes` отдаёт 33 объекта — по одному на
`include_router`, а сами ручки лежат внутри `_IncludedRouter`.

Опасность не в падении, а в тишине: тест-инвариант «под /api/admin нет ручек
без авторизации» на пустом списке проходит и перестаёт что-либо охранять.
Поэтому здесь один обход, который понимает обе раскладки:

- обычный объект с `path` и `methods` — это и есть маршрут;
- `Mount`/`Router` с `.routes` — спускаемся внутрь;
- `_IncludedRouter` (Starlette 1.x) — берём `effective_candidates()`: это тот же
  набор ручек с уже применённым префиксом, и у него есть `dependant` и `endpoint`.

Публичный `/api/meta` этим не пользуется: ему достаточно схемы OpenAPI
(`routes_meta._routes_from_schema`), где префиксы и конвертеры уже сведены.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def iter_route_objects(app: Any) -> Iterator[Any]:
    """Все объекты-маршруты приложения — с путём, методами и обработчиком.

    Возвращает и `APIRoute` (Starlette 0.41), и `_EffectiveRouteContext`
    (Starlette 1.x): у обоих есть `path`, `methods`, `endpoint` и `dependant`,
    поэтому проверки прав пишутся одинаково для обеих версий.
    """
    seen: set[int] = set()
    yield from _walk(getattr(app.router, "routes", []), seen)


def _walk(items: Any, seen: set[int]) -> Iterator[Any]:
    for item in items:
        key = id(item)
        if key in seen:  # pragma: no cover - защита от циклов в чужом роутере
            continue
        seen.add(key)

        # 1. Готовая ручка: путь + методы. Дальше спускаться некуда.
        if getattr(item, "path", None) and getattr(item, "methods", None):
            yield item
            continue

        # 2. Starlette 1.x: включённый роутер как один объект.
        candidates = getattr(item, "effective_candidates", None)
        if callable(candidates):
            try:
                yield from _walk(candidates(), seen)
            except Exception:  # noqa: BLE001 — диагностика не падает из-за чужой API
                continue
            continue

        # 3. Mount / Router с вложенным списком.
        nested = getattr(item, "routes", None)
        if nested:
            yield from _walk(nested, seen)
            continue

        # 4. Mount с отдельным приложением внутри.
        inner = getattr(item, "app", None)
        inner_routes = getattr(getattr(inner, "router", None), "routes", None)
        if inner_routes:
            yield from _walk(inner_routes, seen)
