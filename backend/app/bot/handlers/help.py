"""GHG6 K1+K3+K4: чат-команда /help (и alias /commands).

- В личке работает для всех, кто пишет боту (не только whitelist) — это всё-таки
  публичный «список команд», скрывать его от случайных людей бесполезно. В групповом
  чате — отвечает только участникам whitelist (так же, как остальные чат-команды).
- В группе admin_only-команды скрыты всегда.
- В личке у админа показываем отдельный блок «🔧 Админ» с admin_only-командами.
- Формат: `<b>/cmd</b> — описание` через `\n`, parse_mode=HTML. Reply на исходное.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.commands_catalog import CommandSpec, visible_for
from app.config import get_settings

router = Router()


def _whitelist_set() -> set[int]:
    return {tg_id for tg_id, _ in get_settings().whitelist_pairs}


def _is_admin(tg_id: int) -> bool:
    return tg_id in get_settings().admin_tg_id_set


def render_help(*, scope: str, is_admin: bool) -> str:
    """Рендерит текст ответа /help.

    Выделена в чистую функцию для теста: на входе скоуп и флаг админства,
    на выходе готовый HTML. Никакого Telegram-IO внутри.
    """
    cmds = visible_for(scope, is_admin=is_admin)  # type: ignore[arg-type]
    public_cmds: list[CommandSpec] = [c for c in cmds if not c.admin_only]
    admin_cmds: list[CommandSpec] = [c for c in cmds if c.admin_only]

    lines: list[str] = ["📖 <b>Доступные команды</b>", ""]
    lines.extend(f"<b>/{c.cmd}</b> — {c.desc_ru}" for c in public_cmds)
    if admin_cmds:
        lines.append("")
        lines.append("🔧 <b>Админ</b>")
        lines.extend(f"<b>/{c.cmd}</b> — {c.desc_ru}" for c in admin_cmds)
    return "\n".join(lines)


@router.message(Command(commands=["help", "commands"]))
async def on_help(message: Message) -> None:
    if message.from_user is None:
        return
    tg_id = message.from_user.id

    is_group = message.chat.type in {"group", "supergroup"}
    if is_group and tg_id not in _whitelist_set():
        return

    scope = "group" if is_group else "private"
    text = render_help(scope=scope, is_admin=_is_admin(tg_id))
    await message.reply(text, parse_mode="HTML", disable_web_page_preview=True)
