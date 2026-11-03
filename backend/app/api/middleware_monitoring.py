"""Middleware метрик: длительность и код ответа каждого запроса (5.2).

Почему отдельным middleware, а не в обработчике ошибок. Обработчик ошибок
видит только исключения, а «медленно» и «много 429» — это не исключения.
Одна точка замера даёт и латентность, и коды, и одинаково работает для ручек,
вебхука и статики.

Почему `BaseHTTPMiddleware`. Он получает `scope` с уже разобранным маршрутом
после `call_next`: значит в метрики попадёт шаблон `/api/hr/employees/{id}`, а
не тысяча разных адресов. Для 404 маршрута нет — там будет `unmatched`, и это
честно: путь сканера не наш маршрут.

Что middleware НЕ делает: не пишет в БД и не ходит в сеть. Запись события —
это операция с deque под коротким локом; сеть (алерт в Telegram) вынесена в
планировщик, иначе медленный Telegram задерживал бы ответ клиенту.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware

from app.services import monitoring


class MonitoringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):  # noqa: ANN001, ANN202 - Starlette
        started = time.perf_counter()
        status_code = 500  # упавший до ответа обработчик считаем серверной ошибкой
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            # В `finally`, а не после `return`: исключение обработчика тоже
            # должно попасть в счётчик, иначе настоящие падения не видны вовсе.
            monitoring.record(
                request.method,
                monitoring.template_path(request),
                status_code,
                (time.perf_counter() - started) * 1000.0,
            )
