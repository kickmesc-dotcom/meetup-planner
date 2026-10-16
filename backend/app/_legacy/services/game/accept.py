"""GHG11(17/18): окно приёма ответов — ОДНО правило для всех механик с приёмом.

Зачем отдельным модулем. Сначала настройка жила прямо в гейте голосовых заданий
(`config.VOICE_WINDOW_MINUTES_BY_MODE`), и «распространить её на случайные
события-призывы» можно было только копипастой — два места, которые потом
разъедутся. Здесь правило одно:

* у каждого режима доставки (`delivery.MODES`) своё окно в конфиге;
* **0 в настройке = «как сейчас»**: берём окно конкретной механики из её
  каталога (`VoiceTask.window_minutes`, `Prompt.ttl_minutes`);
* положительное число — переопределение, одно и то же и для `expires_at`, и для
  текста, который обещает срок человеку.

Механики зовут `window_minutes_for` и подставляют результат в свой срок: так
текст не может разойтись с фактическим окном приёма.
"""
from __future__ import annotations

from app._legacy.services.game.config import (
    ACCEPT_WINDOW_MAX_MINUTES,
    ACCEPT_WINDOW_MINUTES_BY_MODE,
)

__all__ = [
    "ACCEPT_WINDOW_MAX_MINUTES",
    "ACCEPT_WINDOW_MINUTES_BY_MODE",
    "default_window_for_mode",
    "window_minutes_for",
]


def default_window_for_mode(mode: str) -> int:
    """Дефолт настройки окна для режима доставки. Незнакомый режим — 0.

    0 означает «как сейчас» (окно механики из каталога) — безопасный дефолт:
    молча подставить чужое окно хуже, чем оставить поведение неизменным.
    """
    return int(ACCEPT_WINDOW_MINUTES_BY_MODE.get(mode, 0))


def window_minutes_for(*, override_minutes: int, default_minutes: int) -> int:
    """Сколько принимается ответ: окно режима или окно каталога механики. Чистая.

    `override_minutes` — настройка для режима доставки. 0 (а также мусор и
    отрицательное) — «как сейчас»: берём окно из каталога механики.
    """
    try:
        override = int(override_minutes)
    except (TypeError, ValueError):
        return int(default_minutes)
    if override > 0:
        return override
    return int(default_minutes)
