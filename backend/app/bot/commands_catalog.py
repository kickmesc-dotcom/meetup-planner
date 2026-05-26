"""GHG6 K2: единый источник правды по чат-командам бота.

Используется и `/help` (рендерит грид с описаниями), и
`main.py::_register_bot_metadata` (отдаёт `BotCommand` в Telegram, чтобы они
светились в menu-кнопке `[/]`). Дублировать описания в двух местах не нужно —
правишь здесь, всё остальное подхватывает.

Scope:
- `private` — только в личке с ботом;
- `group` — только в группе;
- `both` — в обоих.

Флаги:
- `admin_only` — `/help` в группе скрывает, в личке показывает только если
  спрашивает админ (`ADMIN_TG_IDS`). На уровне самого handler-а команда тоже
  проверяет admin, каталог — только про рендеринг подсказки.
- `hidden` — никогда не показывается в `/help` (но может быть зарегистрирована
  как `BotCommand`, если нужно). Сейчас пусто, оставлено на будущее.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Scope = Literal["private", "group", "both"]


@dataclass(frozen=True)
class CommandSpec:
    cmd: str  # без слэша, lowercase
    desc_ru: str
    scope: Scope
    admin_only: bool = False
    hidden: bool = False


# Порядок здесь = порядок в menu и в `/help`. Группируем по логике:
# навигация → действия → инфо → служебные → админ.
COMMANDS: tuple[CommandSpec, ...] = (
    # --- Навигация / Mini App ---
    CommandSpec("start", "Открыть планер встреч", scope="private"),
    # --- Просмотр ---
    CommandSpec("next", "Ближайшая встреча с RSVP", scope="both"),
    CommandSpec("meetings", "5 ближайших встреч + RSVP", scope="both"),
    CommandSpec("chukhan", "Чухан недели", scope="both"),
    CommandSpec("tasks", "Запланированные задачи бота", scope="both"),
    # --- Действия ---
    CommandSpec("loser", "Назначить лоха дня (ручная рулетка)", scope="both"),
    CommandSpec("phrase", "Прогнать рандомную фразу", scope="both"),
    CommandSpec("nominate", "🎮 Добавить игру в номинации", scope="both"),
    CommandSpec(
        "remove_nominated_game",
        "🗑 Удалить игру из номинаций",
        scope="both",
    ),
    # --- Zaebal-цикл (E11) ---
    CommandSpec(
        "zaebal",
        "Голос «бот заебал» — при кворуме включает паузу",
        scope="both",
    ),
    CommandSpec(
        "zaebal_vote",
        "Запустить общий опрос «бот заебал?»",
        scope="both",
    ),
    # --- Личное / служебное ---
    CommandSpec("whoami", "Мой Telegram ID", scope="private"),
    # --- Админ ---
    CommandSpec(
        "forcechukhan",
        "🔧 Перевыбрать чухана недели",
        scope="both",
        admin_only=True,
    ),
    CommandSpec(
        "zaebal_undo",
        "🔧 Снять активную zaebal-паузу",
        scope="both",
        admin_only=True,
    ),
    CommandSpec(
        "help",
        "Список доступных команд",
        scope="both",
    ),
)


def visible_for(scope: Scope, *, is_admin: bool) -> list[CommandSpec]:
    """Команды для отображения в `/help` под заданным scope и правами.

    - В группе admin_only-команды скрываются всегда (даже если запрашивает
      админ — в общий чат не светим).
    - В личке admin_only показываются только админам.
    - `hidden=True` — никогда не показывается.
    - Команды со `scope='private'` не попадают в групповой `/help`,
      `scope='group'` — в личный.
    """
    out: list[CommandSpec] = []
    for c in COMMANDS:
        if c.hidden:
            continue
        if c.scope != "both" and c.scope != scope:
            continue
        if c.admin_only:
            if scope == "group":
                continue
            if not is_admin:
                continue
        out.append(c)
    return out


def bot_commands_for_scope(scope: Literal["private", "group"]) -> list[CommandSpec]:
    """Список команд для регистрации через `bot.set_my_commands` под scope.

    Telegram BotCommandScope не различает админов, поэтому admin_only-команды
    в menu НЕ попадают (видны только через `/help` в личке у админа).
    """
    out: list[CommandSpec] = []
    for c in COMMANDS:
        if c.hidden or c.admin_only:
            continue
        if c.scope != "both" and c.scope != scope:
            continue
        out.append(c)
    return out
