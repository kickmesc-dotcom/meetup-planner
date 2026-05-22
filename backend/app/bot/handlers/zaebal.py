"""GHG6 E11 — чат-команды /zaebal и /zaebal-vote."""
from __future__ import annotations

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.services.bot_pause import (
    get_active_pause,
    is_paused,
    start_pause,
    stop_pause,
)
from app.services.zaebal import (
    create_zaebal_poll,
    register_zaebal_vote,
    _farewell_phrase,
)

log = structlog.get_logger()
router = Router()


def _whitelist_set() -> set[int]:
    return {tg_id for tg_id, _ in get_settings().whitelist_pairs}


def _is_member(tg_id: int | None) -> bool:
    return bool(tg_id and tg_id in _whitelist_set())


def _is_group_chat(message: Message) -> bool:
    settings = get_settings()
    return (
        settings.group_chat_id is not None
        and message.chat.id == settings.group_chat_id
    )


async def _notify_admin_about_pause(reason: str, duration_days: int) -> None:
    """Личка старшему админу (первый в ADMIN_TG_IDS) о начале паузы.
    Тихо логируем ошибки — личка может не открываться."""
    from app.bot.dispatcher import get_bot

    settings = get_settings()
    if not settings.admin_tg_ids:
        return
    primary = next(iter(settings.admin_tg_id_set), None)
    if primary is None:
        return
    bot = get_bot()
    text = (
        f"⏸ Бот поставлен на паузу.\n"
        f"Причина: <code>{reason}</code>\n"
        f"Длительность: {duration_days} дн."
    )
    try:
        await bot.send_message(primary, text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        log.warning("zaebal.admin_notify_failed", error=str(exc))


@router.message(Command("zaebal"))
async def on_zaebal(message: Message) -> None:
    """Регистрирует голос /zaebal. Чужим — отвечаем, что они не из шестёрки."""
    if not _is_group_chat(message) or not message.from_user:
        return
    if not _is_member(message.from_user.id):
        try:
            await message.reply(
                "Извини, голосовать может только шестёрка.", parse_mode="HTML"
            )
        except Exception:  # noqa: BLE001
            pass
        return

    name = message.from_user.full_name or "кто-то"
    sm = get_sessionmaker()
    async with sm() as session:
        if await is_paused(session):
            try:
                await message.reply(
                    "Бот уже на паузе. Ждём окончания.", parse_mode="HTML"
                )
            except Exception:  # noqa: BLE001
                pass
            return

        count, threshold = await register_zaebal_vote(
            session, tg_id=message.from_user.id
        )

        if count >= threshold:
            # Стартуем паузу.
            from app.services.bot_pause import get_zaebal_settings

            cfg = await get_zaebal_settings(session)
            duration_days = int(cfg["duration_days"])
            try:
                await start_pause(
                    session,
                    duration_days=duration_days,
                    reason="zaebal_threshold",
                    started_by_tg_id=message.from_user.id,
                )
            except ValueError as exc:
                log.info("zaebal.start_pause_failed", error=str(exc))
                return
            from app.services.zaebal import clear_zaebal_votes

            await clear_zaebal_votes(session)
            farewell = _farewell_phrase()
            try:
                await message.answer(
                    f"<i>{farewell}</i>\n\n"
                    f"⏸ Активность бота приостановлена на <b>{duration_days} дн.</b> "
                    f"Снять — /zaebal_undo или из админки.",
                    parse_mode="HTML",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("zaebal.farewell_send_failed", error=str(exc))
            await _notify_admin_about_pause("zaebal_threshold", duration_days)
            return

    # Порог ещё не набран — просто подтверждаем.
    needed = max(0, threshold - count)
    try:
        await message.reply(
            f"😔 {name}, ок. Голосов /zaebal в этом часе: <b>{count}/{threshold}</b>. "
            f"Ещё <b>{needed}</b> — и бот замолчит.",
            parse_mode="HTML",
        )
    except Exception:  # noqa: BLE001
        pass


@router.message(Command("zaebal_vote", "zaebalvote"))
async def on_zaebal_vote(message: Message) -> None:
    if not _is_group_chat(message) or not message.from_user:
        return
    if not _is_member(message.from_user.id):
        try:
            await message.reply(
                "Извини, голосование может запустить только шестёрка.",
                parse_mode="HTML",
            )
        except Exception:  # noqa: BLE001
            pass
        return

    from app.bot.dispatcher import get_bot

    initiator_label = message.from_user.full_name or "Кто-то"
    sm = get_sessionmaker()
    async with sm() as session:
        if await is_paused(session):
            try:
                await message.reply("Бот уже на паузе.", parse_mode="HTML")
            except Exception:  # noqa: BLE001
                pass
            return
        result = await create_zaebal_poll(
            session, get_bot(), initiator_label=initiator_label, auto=False
        )
    if result is None:
        try:
            await message.reply(
                "Не удалось создать опрос (проверь конфиг чата).",
                parse_mode="HTML",
            )
        except Exception:  # noqa: BLE001
            pass


@router.message(Command("zaebal_undo"))
async def on_zaebal_undo(message: Message) -> None:
    """Снять паузу из чата — только админу."""
    if not _is_group_chat(message) or not message.from_user:
        return
    settings = get_settings()
    if message.from_user.id not in settings.admin_tg_id_set:
        return
    sm = get_sessionmaker()
    async with sm() as session:
        pause = await get_active_pause(session)
        if pause is None:
            try:
                await message.reply("Активной паузы нет.", parse_mode="HTML")
            except Exception:  # noqa: BLE001
                pass
            return
        await stop_pause(session)
    try:
        await message.answer("▶️ Бот снова в эфире.", parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        log.warning("zaebal.undo_send_failed", error=str(exc))
