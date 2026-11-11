"""RUM: приём и сводка Core Web Vitals с устройств (этап 5, AAA_ROADMAP).

Зачем. `monitoring.py` отвечает «сколько запросов упало и как быстро ответил
сервер», но не отвечает, как это пережил телефон. Метрики браузера приходят
сюда, в кольцевой буфер, и сводка считается p75 по устройству — именно этот
порог Lighthouse считает «хорошим», поэтому экран и CI говорят на одном языке.

Почему в памяти, а не в базе. Частота низкая (несколько отчётов на человека в
день), а писать каждую метрику в Postgres ради дашборда — это лишняя нагрузка
на боевую базу и лишние персональные следы. Окно в 24 часа отвечает на вопрос
«как дела сегодня», а не «что было месяц назад».
"""

from __future__ import annotations

import math
import threading
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# 24 часа: RUM приходит редко, и окно должно переживать ночь.
WINDOW_SEC = 24 * 60 * 60
# Потолок памяти: 5000 отчётов — это месяцы для пилота и ~0,5 МБ.
MAX_EVENTS = 5000
# Порог «хорошо» из Core Web Vitals. Числа различаются по метрике.
GOOD_LIMITS: dict[str, float] = {
    "LCP": 2500.0,
    "INP": 200.0,
    "CLS": 0.1,
    "FCP": 1800.0,
    "TTFB": 800.0,
}
# Метрики, где меньше — лучше, но значение уже в миллисекундах/долях.
METRIC_NAMES = frozenset(GOOD_LIMITS)


@dataclass(frozen=True)
class Vital:
    at: float
    name: str
    value: float
    device: str
    path: str
    build: str


def _percentile(values: list[float], q: float) -> float:
    """p75 по ближайшему рангу: без интерполяции, чтобы число было реальным."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return round(ordered[index], 3)


class Rum:
    def __init__(self) -> None:
        self._events: deque[Vital] = deque(maxlen=MAX_EVENTS)
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def record(
        self,
        *,
        name: str,
        value: float,
        device: str = "",
        path: str = "",
        build: str = "",
        now: datetime | None = None,
    ) -> None:
        moment = now or datetime.now(UTC)
        with self._lock:
            self._events.append(
                Vital(
                    at=moment.timestamp(),
                    name=name,
                    value=float(value),
                    device=device or "unknown",
                    path=path,
                    build=build,
                )
            )

    def snapshot(self, *, now: datetime | None = None) -> dict:
        """Сводка по окну: p75, p95, число и доля «хороших» на устройство."""
        moment = now or datetime.now(UTC)
        cutoff = (moment - timedelta(seconds=WINDOW_SEC)).timestamp()
        with self._lock:
            events = [event for event in self._events if event.at >= cutoff]

        grouped: dict[str, dict[str, list[Vital]]] = {}
        for event in events:
            grouped.setdefault(event.name, {}).setdefault(event.device, []).append(event)

        metrics: dict[str, dict[str, dict]] = {}
        for name, by_device in grouped.items():
            limit = GOOD_LIMITS.get(name)
            devices: dict[str, dict] = {}
            for device, items in by_device.items():
                values = [item.value for item in items]
                good = (
                    sum(1 for value in values if value <= limit) / len(values)
                    if limit is not None and values
                    else 0.0
                )
                devices[device] = {
                    "count": len(values),
                    "p75": _percentile(values, 0.75),
                    "p95": _percentile(values, 0.95),
                    "good_share": round(good, 3),
                }
            metrics[name] = devices

        return {
            "window_seconds": WINDOW_SEC,
            "events": len(events),
            "metrics": metrics,
            "top_paths": [
                {"path": path, "count": count}
                for path, count in Counter(event.path for event in events).most_common(5)
                if path
            ],
            "builds": [
                {"build": build, "count": count}
                for build, count in Counter(event.build for event in events).most_common(5)
                if build
            ],
        }


rum = Rum()
