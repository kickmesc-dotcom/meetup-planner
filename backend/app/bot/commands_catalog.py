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


# SemiTaskBot: каталог рабочих команд ресторанного бота.
#
# Наследные шуточные команды (чухан/лох/червь/музыка/ачивки) из каталога
# УБРАНЫ — их брендинг в новом продукте недопустим. Сами обработчики живут
# в `app/_legacy` и не подключаются к диспетчеру.
#
# Порядок здесь = порядок в menu и в `/help`.
COMMANDS: tuple[CommandSpec, ...] = (
    # --- Навигация ---
    CommandSpec("start", "Открыть меню бота", scope="private"),
    CommandSpec("menu", "Главное меню: чек-лист, задачи, ссылки", scope="private"),
    # --- Личное / служебное ---
    CommandSpec("whoami", "Мой Telegram ID", scope="private"),
    # Сводка смены: в каталоге видна всем, но обработчик отвечает только АУП.
    CommandSpec("report", "Отчёт смены (руководителю)", scope="private"),
    # Прогноз второй ступени: обработчик пускает только админа.
    CommandSpec("escalations", "Эскалации: что уйдёт админам", scope="private"),
    CommandSpec("help", "Список доступных команд", scope="both"),
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
