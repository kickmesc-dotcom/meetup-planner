"""GHG10: рубильник игровой системы и гейтинг по рангам.

Задание: «реализовать так, чтобы в случае возникновения проблем/тормозов на
хостинге/БД — стопнуть или выпилить модуль ачивок/левелов одним махом, не
затронув всю остальную работу бота».

Отсюда два правила:

1. **Рубильник** — `game.enabled` в `admin_config`. По умолчанию **выключен**
   (поэтапная выкатка, как `worm_master.enabled`): выкатываем код, включаем
   кнопкой. Все точки вызова обязаны начинаться с `await is_game_enabled(...)`
   и при `False` выходить молча — без начислений, анонсов и запросов.
2. **Гейтинг — дополнительный слой**, а не замена прав. Админ-ручки остаются
   админскими; ранг лишь добавляет требование поверх. Исключение по
   отладочным TG-id (`game.debug_tg_ids`, «Серж нео») задаётся конфигом.

Чистая часть (`required_level`, `has_feature`) отделена от чтения конфига,
чтобы тестироваться без БД.
"""
from __future__ import annotations

from app.services.admin_config import (
    get_game_debug_tg_ids,
    get_game_enabled,
)
from app.services.game.config import LEVEL_UNLOCKS


async def is_game_enabled(session) -> bool:
    """Главный рубильник. Выключен → весь игровой модуль молчит."""
    return await get_game_enabled(session)


async def is_debug_exempt(session, telegram_id: int | None) -> bool:
    """Отладочное исключение из гейтинга («Серж нео»).

    Список TG-id живёт в `admin_config`, а не в коде: состав отладчиков может
    меняться без деплоя.
    """
    if telegram_id is None:
        return False
    return telegram_id in await get_game_debug_tg_ids(session)


def required_level(feature: str) -> int | None:
    """С какого уровня открывается фича. `None` — фича не гейтится рангом."""
    for level, features in sorted(LEVEL_UNLOCKS.items()):
        if feature in features:
            return level
    return None


def has_feature(level: int, feature: str, *, debug: bool = False) -> bool:
    """Доступна ли фича на этом уровне.

    `debug=True` (см. `is_debug_exempt`) — доступна всегда.
    Неизвестная фича не гейтится (возвращаем True): гейтинг — дополнительный
    слой поверх существующих прав, и он не должен ломать старое поведение при
    опечатке в коде фичи.
    """
    if debug:
        return True
    need = required_level(feature)
    if need is None:
        return True
    return level >= need
