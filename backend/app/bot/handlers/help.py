"""GHG6 K1+K3+K4: чат-команда /help (и alias /commands).

- В личке работает для всех, кто пишет боту (не только whitelist) — это всё-таки
  публичный «список команд», скрывать его от случайных людей бесполезно. В групповом
  чате — отвечает только участникам whitelist (так же, как остальные чат-команды).
- В группе admin_only-команды скрыты всегда.
- В личке у админа показываем отдельный блок «🔧 Админ» с admin_only-командами.
- Формат: `<b>/cmd</b> — описание` через `\n`, parse_mode=HTML. Reply на исходное.

GHG7 P1.4: к строке /zaebal добавляется badge ⏸️ с оставшимся временем
паузы, если в данный момент активен `BotPause`. Через `BotCommand.description`
это сделать нельзя (TG кеширует и rate-limit'ит обновления setMyCommands),
поэтому badge живёт только в нашем `/help` — он рендерится по запросу и
всегда отражает актуальное состояние.
"""
from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.commands_catalog import CommandSpec, visible_for
from app.config import get_settings
from app.db.base import get_sessionmaker
from app.services.bot_pause import get_active_pause

router = Router()


def _whitelist_set() -> set[int]:
    return {tg_id for tg_id, _ in get_settings().whitelist_pairs}


def _is_admin(tg_id: int) -> bool:
    return tg_id in get_settings().admin_tg_id_set


def _format_remaining(ends_at: datetime, *, now: datetime | None = None) -> str:
    """GHG7 P1.4: «1д 4ч 12м» или «43м» или «<1м» для остатка до конца паузы.

    Чистая функция — для теста. Если `ends_at` уже в прошлом (race condition
    между чтением БД и рендером), возвращаем «<1м», а не отрицательное —
    handler в этот момент покажет «активна», и пауза скоро будет снята
    `maybe_auto_restore`.
    """
    now = now or datetime.now(timezone.utc)
    delta = ends_at - now
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 60:
        return "<1м"
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts: list[str] = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    # Минуты показываем только если днями/часами не покрыто полностью,
    # либо если это единственная единица (без дней и часов).
    if minutes or not parts:
        parts.append(f"{minutes}м")
    return " ".join(parts)


def render_help(
    *,
    scope: str,
    is_admin: bool,
    paused_until: datetime | None = None,
    now: datetime | None = None,
) -> str:
    """Рендерит текст ответа /help.

    Выделена в чистую функцию для теста: на входе скоуп и флаг админства,
    на выходе готовый HTML. Никакого Telegram-IO внутри.

    GHG7 P1.4: если `paused_until` задан и > now — к строке `/zaebal`
    дописывается `⏸️ пауза N` (тиктайн-таймер до разморозки). Если в
    данный момент паузы нет — рендер прежний, обратно совместим со
    старыми вызовами (default `paused_until=None`).
    """
    cmds = visible_for(scope, is_admin=is_admin)  # type: ignore[arg-type]
    public_cmds: list[CommandSpec] = [c for c in cmds if not c.admin_only]
    admin_cmds: list[CommandSpec] = [c for c in cmds if c.admin_only]

    def _line(c: CommandSpec) -> str:
        base = f"<b>/{c.cmd}</b> — {c.desc_ru}"
        if c.cmd == "zaebal" and paused_until is not None:
            base += f"  ⏸️ пауза {_format_remaining(paused_until, now=now)}"
        return base

    lines: list[str] = ["📖 <b>Доступные команды</b>", ""]
    lines.extend(_line(c) for c in public_cmds)
    if admin_cmds:
        lines.append("")
        lines.append("🔧 <b>Админ</b>")
        lines.extend(_line(c) for c in admin_cmds)
    return "\n".join(lines)


@router.message(Command(commands=["help", "commands"]))
async def on_help(message: Message) -> None:
    if message.from_user is None:
        return
    tg_id = message.from_user.id

    is_group = message.chat.type in {"group", "supergroup"}
    if is_group and tg_id not in _whitelist_set():
        return

    # GHG7 P1.4: подгружаем активную паузу для индикации в /help.
    sm = get_sessionmaker()
    paused_until: datetime | None = None
    async with sm() as session:
        pause = await get_active_pause(session)
        if pause is not None:
            paused_until = pause.ends_at

    scope = "group" if is_group else "private"
    text = render_help(
        scope=scope,
        is_admin=_is_admin(tg_id),
        paused_until=paused_until,
    )
    await message.reply(text, parse_mode="HTML", disable_web_page_preview=True)
