"""Мониторинг запросов: ошибки, латентность, алерты (B2B_PLATFORM_PLAN, 5.2).

Зачем в памяти, а не Prometheus. Пока один процесс и один контейнер, внешний
сборщик — это ещё один сервис, который надо поднимать, обновлять и оплачивать.
Здесь нужен ответ на три вопроса: «сколько запросов», «сколько из них упало»,
«стало ли медленнее» — и алерт, когда ответ меняется. Когда процессов станет
больше одного, счётчики переедут в общий стор, а интерфейс `snapshot()` останется.

Почему окно, а не счётчики «за всё время». Число пятисотых с момента запуска
никогда не уменьшается: через месяц оно всегда «много», и алерт перестаёт
значить что-либо. Окно в 15 минут — это «как дела сейчас».

Почему путь шаблонизируется. `/api/hr/employees/123` и `/api/hr/employees/124`
для монитора — один маршрут. Иначе топ путей превращается в список конкретных
людей, а не в список проблемных ручек. Middleware берёт шаблон из
`request.scope["route"].path`, то есть ровно тот путь, который объявлен в коде.

Почему алерт не на каждый пятисотый. Один упавший запрос из десяти — это 10%,
но это ещё не падение. Алерт включается, только когда есть и доля (>=5%), и
объём (>=20 запросов): иначе ночной единичный сбой будил бы владельца.

Почему кулдаун. Алерт, который приходит каждые пять минут, отключают — и тогда
не видят настоящего падения. После отправки молчим полчаса, даже если стало
хуже: следующий алерт скажет «всё ещё плохо» уже с новыми цифрами.
"""

from __future__ import annotations

import math
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Окно «сейчас». 15 минут — достаточно, чтобы заметить падение, и мало, чтобы
# старый всплеск держал алерт включённым.
WINDOW_SEC = 15 * 60
# Сколько событий помним. 4000 запросов за 15 минут — это ~4 rps; больше в
# одном контейнере не бывает, а память ограничена тарифом 0,5 ГБ.
MAX_EVENTS = 4000
# Последние ошибки: без них в снапшоте видно «что-то упало», но не что именно.
MAX_ERRORS = 50

ERROR_RATE_THRESHOLD = 0.05
MIN_REQUESTS_FOR_ALERT = 20
P95_THRESHOLD_MS = 2000.0
ALERT_COOLDOWN_SEC = 30 * 60
# 5xx — это «сломалось у нас». 4xx — «клиент ошибся», их не алертим: иначе
# поток 401 от чужого сканера выглядел бы падением.
SERVER_ERROR = 500


@dataclass(frozen=True)
class Event:
    at: float
    method: str
    path: str
    status: int
    duration_ms: float


@dataclass(frozen=True)
class ErrorHit:
    at: datetime
    method: str
    path: str
    status: int
    duration_ms: float


@dataclass
class Snapshot:
    window_seconds: int
    requests: int
    errors: int
    error_rate: float
    p50_ms: float
    p95_ms: float
    slowest_ms: float
    top_paths: list[dict]
    top_errors: list[dict]
    last_error: dict | None
    alert: str | None = None
    extra: dict = field(default_factory=dict)


class Metrics:
    """Кольцевой буфер событий + расчёт сводки по окну."""

    def __init__(self, *, window_sec: int = WINDOW_SEC, max_events: int = MAX_EVENTS) -> None:
        self._window = window_sec
        self._events: deque[Event] = deque(maxlen=max_events)
        self._errors: deque[ErrorHit] = deque(maxlen=MAX_ERRORS)
        self._lock = threading.Lock()
        self._alerted_at: float | None = None

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._errors.clear()
            self._alerted_at = None

    def record(
        self,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        *,
        now: float | None = None,
    ) -> None:
        moment = time.monotonic() if now is None else now
        event = Event(
            at=moment,
            method=method.upper(),
            path=path or "unmatched",
            status=int(status),
            duration_ms=max(0.0, float(duration_ms)),
        )
        with self._lock:
            self._events.append(event)
            if event.status >= SERVER_ERROR:
                self._errors.append(
                    ErrorHit(
                        at=datetime.now(UTC),
                        method=event.method,
                        path=event.path,
                        status=event.status,
                        duration_ms=event.duration_ms,
                    )
                )
            self._prune(moment)

    def _prune(self, now: float) -> None:
        border = now - self._window
        while self._events and self._events[0].at < border:
            self._events.popleft()

    @staticmethod
    def _percentile(values: list[float], share: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        # `ceil-1`, а не `round`: на трёх значениях p95 должен быть максимумом,
        # иначе «медленнее всего» и p95 contradict друг друга.
        index = max(0, min(len(ordered) - 1, math.ceil(share * len(ordered)) - 1))
        return ordered[index]

    def snapshot(self, *, now: float | None = None) -> Snapshot:
        moment = time.monotonic() if now is None else now
        with self._lock:
            self._prune(moment)
            events = list(self._events)
            errors = list(self._errors)[-10:]
        total = len(events)
        failed = [e for e in events if e.status >= SERVER_ERROR]
        durations = [e.duration_ms for e in events]
        by_path = Counter((e.path, e.status) for e in events if e.status >= SERVER_ERROR)
        top_errors = [
            {"path": path, "status": status, "count": count}
            for (path, status), count in by_path.most_common(5)
        ]
        busiest = Counter(e.path for e in events).most_common(5)
        last = errors[-1] if errors else None
        data = Snapshot(
            window_seconds=self._window,
            requests=total,
            errors=len(failed),
            error_rate=(len(failed) / total) if total else 0.0,
            p50_ms=self._percentile(durations, 0.50),
            p95_ms=self._percentile(durations, 0.95),
            slowest_ms=max(durations) if durations else 0.0,
            top_paths=[{"path": path, "count": count} for path, count in busiest],
            top_errors=top_errors,
            last_error=(
                {
                    "at": last.at.isoformat(),
                    "method": last.method,
                    "path": last.path,
                    "status": last.status,
                    "duration_ms": round(last.duration_ms, 1),
                }
                if last is not None
                else None
            ),
        )
        reason = self._reason(data)
        data.alert = reason
        return data

    @staticmethod
    def _reason(data: Snapshot) -> str | None:
        if data.requests < MIN_REQUESTS_FOR_ALERT:
            return None
        if data.error_rate >= ERROR_RATE_THRESHOLD:
            return "errors"
        if data.p95_ms >= P95_THRESHOLD_MS:
            return "latency"
        return None

    def take_alert(self, *, now: float | None = None) -> str | None:
        """Вернуть причину алерта, если пора, и включить кулдаун.

        Отдельно от `snapshot`: сводку читают сколько угодно раз, а алерт
        отправляется один раз за окно. Иначе экран админки, который обновляется,
        сам бы «отправлял» алерты.
        """
        moment = time.monotonic() if now is None else now
        reason = self.snapshot(now=moment).alert
        if reason is None:
            return None
        with self._lock:
            if self._alerted_at is not None and moment - self._alerted_at < ALERT_COOLDOWN_SEC:
                return None
            self._alerted_at = moment
        return reason

    def alert_text(self, reason: str, *, now: float | None = None) -> str:
        """Текст для Telegram: цифры и что смотреть, без простыни."""
        data = self.snapshot(now=now)
        head = "🔴 Падение API" if reason == "errors" else "🟠 API замедлился"
        lines = [
            f"{head}: {data.errors} из {data.requests} запросов за "
            f"{data.window_seconds // 60} мин ({data.error_rate:.0%}), p95 "
            f"{data.p95_ms:.0f} мс.",
        ]
        if data.top_errors:
            worst = data.top_errors[0]
            lines.append(f"Чаще всего: {worst['path']} → {worst['status']} ({worst['count']}).")
        if data.last_error:
            lines.append(
                f"Последняя: {data.last_error['method']} {data.last_error['path']} "
                f"{data.last_error['status']}."
            )
        lines.append("Подробности: кабинет → Платформа.")
        return "\n".join(lines)


# Один экземпляр на процесс: middleware и ручки должны видеть одни и те же
# цифры. В тестах сбрасывается `reset()`.
metrics = Metrics()


def record(
    method: str,
    path: str,
    status: int,
    duration_ms: float,
    *,
    now: float | None = None,
) -> None:
    metrics.record(method, path, status, duration_ms, now=now)


def snapshot(*, now: float | None = None) -> Snapshot:
    return metrics.snapshot(now=now)


def take_alert(*, now: float | None = None) -> str | None:
    return metrics.take_alert(now=now)


def reset() -> None:
    metrics.reset()


def template_path(request) -> str:  # noqa: ANN001
    """Путь маршрута-шаблона, а не конкретный адрес запроса.

    `request.scope["route"]` появляется только после маршрутизации, поэтому
    для 404 берём `unmatched`: складывать в топ случайные адреса сканеров
    бессмысленно.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or "unmatched"
