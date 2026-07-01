"""P4: чат-команды для шестёрки.

Все четыре команды доступны только участникам whitelist (WHITELIST_TG_IDS).
Чужие вызовы игнорируются молча — не хотим, чтобы бот «отзывался» вне группы.

Реролл чухана НЕ выносим в чат (по чеклисту) — остаётся в админке.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import and_, select

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import Meeting, MeetingAttendance, User

log = structlog.get_logger()
router = Router()


RSVP_EMOJI = {0: "❔", 1: "✅", 2: "🤔", 3: "🙅"}


def _whitelist_set() -> set[int]:
    return {tg_id for tg_id, _ in get_settings().whitelist_pairs}


def _is_member(tg_id: int | None) -> bool:
    if tg_id is None:
        return False
    return tg_id in _whitelist_set()


# ---------------------- C1: /phrase ----------------------

@router.message(Command("phrase"))
async def on_phrase(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return
    from app.bot.dispatcher import get_bot
    from app.services.random_phrases import run_random_phrases_job

    try:
        await run_random_phrases_job(get_bot())
    except Exception:
        log.exception("chat.phrase_failed", by=message.from_user.id)
        await message.answer("⚠️ Не получилось сочинить фразу — посмотри логи.")


# ---------------------- T3.4: /advice («магический шар») ----------------------

@router.message(Command("advice"))
async def on_advice(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return
    await reply_advice(message)


async def reply_advice(message: Message) -> bool:
    """Сгенерировать и отправить совет (reply на исходное сообщение).

    Возвращает True если совет отправлен (или попытались), False если фича
    выключена / пул пуст — вызывающий код (bot_reactions альт-триггер) по
    этому решает, продолжать ли обычный сценарий. Уважает тогл
    `advice.enabled`.
    """
    from app.services.admin_config import get_advice_enabled, get_advice_phrases
    from app.services.advice import pick_advice

    sm = get_sessionmaker()
    async with sm() as session:
        if not await get_advice_enabled(session):
            return False
        phrases = await get_advice_phrases(session)
    text = pick_advice(phrases)
    if not text:
        return False
    try:
        await message.reply(f"🔮 {text}", parse_mode="HTML")
    except Exception:
        log.exception("chat.advice_failed", by=message.from_user.id if message.from_user else None)
    return True


# ---------------------- T3.6 (в): /punish (только червь-господин) ----------------------

def _extract_target_from_entities(message: Message) -> str | None:
    """Цель наказания из сущностей сообщения (приоритетнее текстового разбора).

    `mention` (@username) — берём как есть. `text_mention` (без username) —
    отдаём display_name из профиля, чтобы хотя бы упомянуть человека текстом.
    None если явных упоминаний нет — тогда вызывающий код пробует текст.
    """
    if not message.entities or not message.text:
        return None
    for ent in message.entities:
        if ent.type == "mention":
            return message.text[ent.offset : ent.offset + ent.length]
        if ent.type == "text_mention" and ent.user:
            return ent.user.full_name or (
                f"@{ent.user.username}" if ent.user.username else None
            )
    return None


@router.message(Command(commands=["punish", "наказать"]))
async def on_punish(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return
    # Явная команда → отповедь не-господину (QOL). Хештег #punish (альт-триггер
    # из bot_reactions) вызывает _handle_punish с deny_if_not_master=False, чтобы
    # случайный тег в сообщении не спамил «ты мне не господин».
    await _handle_punish(message, deny_if_not_master=True)


async def _handle_punish(message: Message, *, deny_if_not_master: bool = False) -> bool:
    """Червь-господин натравливает бота на недруга. Гейт жёстче whitelist:
    вызвать может ТОЛЬКО текущий червь-господин, и только при включённых
    `worm_master.enabled` + `worm_master.punish_enabled`.

    `deny_if_not_master`: если True и вызвал НЕ господин — бот отвечает
    отповедью («ты мне не господин, слушаюсь только его»). False (хештег) —
    тихий no-op, как раньше. Отповедь даём только когда режим/тогл включены —
    иначе выдали бы существование фичи тем, кому она недоступна.

    Возвращает True, если что-то ответили (для альт-триггера #punish из
    bot_reactions — чтобы тот понял, что сценарий отработал)."""
    from app.services.admin_config import (
        get_worm_punish,
        is_worm_master_enabled,
        is_worm_master_punish_enabled,
    )
    from app.services.loser import get_current_worm
    from app.services.phrase_weights import (
        WORM_PUNISH_USE_COUNTS_KEY,
        get_use_counts,
        increment_use_count,
    )
    from app.services.worm_master import choose, extract_punish_target, render

    sm = get_sessionmaker()
    async with sm() as session:
        if not await is_worm_master_enabled(session):
            return False
        if not await is_worm_master_punish_enabled(session):
            return False
        caller = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        if caller is None:
            return False
        worm = await get_current_worm(session)
        if worm is None or worm.user_id != caller.id:
            if not deny_if_not_master:
                # Хештег-триггер — тихо игнорируем (случайный #punish не спамит).
                return False
            # QOL: явная команда от не-господина → бот ставит на место.
            master_name: str | None = None
            if worm is not None:
                master = await session.get(User, worm.user_id)
                master_name = master.display_name if master else None
            await _reply_punish_denied(message, master_name)
            return True

        # Цель: сначала сущности (@mention/text_mention), потом текстовый фолбэк.
        target = _extract_target_from_entities(message) or extract_punish_target(
            message.text
        )
        if not target:
            await message.answer(
                "⚔️ Кого карать-то? Использование: <code>/punish @недруг</code>",
                parse_mode="HTML",
            )
            return True

        pool = await get_worm_punish(session)
        counts = await get_use_counts(session, WORM_PUNISH_USE_COUNTS_KEY)
        raw = choose(pool, counts)
        if raw is None:
            return False
        await increment_use_count(session, WORM_PUNISH_USE_COUNTS_KEY, raw)
        await session.commit()
    text = render(raw, target=target)
    try:
        await message.answer(f"⚔️ {text}", parse_mode="HTML")
    except Exception:
        log.exception("chat.punish_failed", by=message.from_user.id)
    return True


# ---------------------- T3.6.8: /отвали (только червь-господин) ----------------------

@router.message(Command(commands=["отвали", "otvali"]))
async def on_otvali(message: Message) -> None:
    """Господин затыкает подхалима: /отвали → выключаем тумблер поддакивания
    в админке (worm_master.yes_enabled=false). Пользователь потом вернёт его
    руками в Mini App. Вызвать может ТОЛЬКО текущий червь-господин при включённом
    режиме; для остальных — тихий no-op."""
    if not message.from_user or not _is_member(message.from_user.id):
        return
    from app.services.admin_config import (
        is_worm_master_enabled,
        is_worm_master_yes_enabled,
        set_worm_master_yes_enabled,
    )
    from app.services.loser import get_current_worm

    sm = get_sessionmaker()
    async with sm() as session:
        if not await is_worm_master_enabled(session):
            return
        caller = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        if caller is None:
            return
        worm = await get_current_worm(session)
        if worm is None or worm.user_id != caller.id:
            # Не господин — тихо игнорируем.
            return
        if not await is_worm_master_yes_enabled(session):
            # Уже выключено — мягко подтвердим, чтобы команда не «молчала».
            await message.reply("🤫 Я и так нем как рыба, мой господин.")
            return
        await set_worm_master_yes_enabled(session, False)
    try:
        await message.reply("🤫 Умолкаю, повелитель. Поддакивания выключены.")
    except Exception:
        log.exception("chat.otvali_failed", by=message.from_user.id)


async def _reply_punish_denied(message: Message, master_name: str | None) -> None:
    """QOL: отповедь не-господину, дёрнувшему /punish. Если червь назначен —
    называем его по имени (named-пул), иначе безымянная отповедь."""
    import random

    from app.services.worm_master import (
        DEFAULT_WORM_PUNISH_DENIED,
        DEFAULT_WORM_PUNISH_DENIED_NAMED,
        render,
    )

    if master_name:
        raw = random.choice(DEFAULT_WORM_PUNISH_DENIED_NAMED)
        text = render(raw, username=master_name)
    else:
        text = random.choice(DEFAULT_WORM_PUNISH_DENIED)
    try:
        await message.reply(f"🪱 {text}", parse_mode="HTML")
    except Exception:
        log.exception("chat.punish_denied_failed", by=message.from_user.id)


# ---------------------- C2: /loser ----------------------

@router.message(Command("loser"))
async def on_loser(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return

    from app.bot.dispatcher import get_bot
    from app.services.loser import CooldownError, compose_loser_message, roll_loser

    settings = get_settings()
    chat_id = settings.group_chat_id
    bot = get_bot()

    sm = get_sessionmaker()
    async with sm() as session:
        caller = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        if caller is None:
            log.warning("chat.loser_caller_not_in_db", tg_id=message.from_user.id)
            return

        async def _announce(roll, loser, extras=None):
            target = chat_id if chat_id else message.chat.id
            # GHG8 P3: «мог бы стать %name%, но ДР» — перед основным постом.
            if extras is not None and getattr(extras, "immunity_skipped", None):
                from app.services.birthday_immunity import announce_immunity_skips

                await announce_immunity_skips(
                    bot, target, extras.immunity_skipped
                )
            text = compose_loser_message(
                loser_name=loser.display_name,
                reason_text=roll.reason_text or "",
                roller_name=caller.display_name,
                extras=extras,
                header_emoji="🤡",
                header_label="Автолох",
            )
            await bot.send_message(chat_id=target, text=text, parse_mode="HTML")

        try:
            # GHG7 P9.1.a: /loser — это «автолох-дуэль» (🤡), НЕ «лох дня» (👑).
            # source="duel" исключает ролл из статистики/титулов (P9.2).
            await roll_loser(
                session, rolled_by=caller, on_announce=_announce, source="duel"
            )
        except CooldownError as exc:
            mins = int(exc.remaining.total_seconds() // 60)
            await message.answer(f"⏳ Ещё рано — подожди ~{mins} мин.")
        except Exception:
            log.exception("chat.loser_failed", by=message.from_user.id)
            await message.answer("⚠️ Не получилось.")


# ---------------------- C3: /meetings ----------------------

@router.message(Command("meetings"))
async def on_meetings(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return

    settings = get_settings()
    tz = ZoneInfo(settings.scheduler_tz)
    tz_label = "МСК" if settings.scheduler_tz == "Europe/Moscow" else settings.scheduler_tz
    now = datetime.now(timezone.utc)

    sm = get_sessionmaker()
    async with sm() as session:
        meetings = list((await session.scalars(
            select(Meeting)
            .where(and_(Meeting.starts_at >= now, Meeting.status != "cancelled"))
            .order_by(Meeting.starts_at.asc())
            .limit(5)
        )).all())
        if not meetings:
            await message.answer("📭 Запланированных встреч нет.")
            return

        meeting_ids = [m.id for m in meetings]
        attendance = list((await session.scalars(
            select(MeetingAttendance).where(
                MeetingAttendance.meeting_id.in_(meeting_ids)
            )
        )).all())
        user_ids = {a.user_id for a in attendance}
        users_by_id = {
            u.id: u
            for u in (await session.scalars(
                select(User).where(User.id.in_(user_ids))
            )).all()
        }
        att_by_meeting: dict[int, list[MeetingAttendance]] = {}
        for a in attendance:
            att_by_meeting.setdefault(a.meeting_id, []).append(a)

    lines: list[str] = [f"📅 <b>Ближайшие встречи ({len(meetings)}):</b>"]
    for m in meetings:
        starts_local = m.starts_at.astimezone(tz).strftime("%a %d.%m %H:%M")
        ends_local = m.ends_at.astimezone(tz).strftime("%H:%M")
        lines.append("")
        lines.append(f"<b>{m.title}</b>")
        lines.append(f"  {starts_local}–{ends_local} {tz_label}")
        if m.location:
            lines.append(f"  📍 {m.location}")
        rsvp_line_parts: list[str] = []
        for a in att_by_meeting.get(m.id, []):
            u = users_by_id.get(a.user_id)
            name = u.display_name if u else f"#{a.user_id}"
            rsvp_line_parts.append(f"{RSVP_EMOJI.get(a.rsvp, '❔')} {name}")
        if rsvp_line_parts:
            lines.append("  " + ", ".join(rsvp_line_parts))

    await message.answer("\n".join(lines))


# ---------------------- GHG8 P4.1.d: /top ----------------------

@router.message(Command("top"))
async def on_top(message: Message) -> None:
    """Топы лохов/чуханов за всё время — текстовое зеркало экрана «Профиль →
    Топы» в Mini App (P4.1.d: «команда /top ведёт туда же»)."""
    if not message.from_user or not _is_member(message.from_user.id):
        return
    from sqlalchemy import func as _func

    from app.db.models import WeeklyChukhan
    from app.services.loser import loser_stats

    sm = get_sessionmaker()
    async with sm() as session:
        loser_counts = await loser_stats(session)
        chukhan_rows = (
            await session.execute(
                select(WeeklyChukhan.user_id, _func.count())
                .where(WeeklyChukhan.posted_at.is_not(None))
                .group_by(WeeklyChukhan.user_id)
                .order_by(_func.count().desc())
            )
        ).all()
        uids = set(loser_counts) | {int(uid) for uid, _ in chukhan_rows}
        names = {
            u.id: u.display_name
            for u in (
                await session.scalars(select(User).where(User.id.in_(uids)))
            ).all()
        } if uids else {}

    def _block(title: str, pairs: list[tuple[int, int]], empty: str) -> list[str]:
        out = [f"<b>{title}</b>"]
        if not pairs:
            out.append(f"  {empty}")
            return out
        medals = ("🥇", "🥈", "🥉")
        for i, (uid, cnt) in enumerate(pairs):
            mark = medals[i] if i < len(medals) else f"{i + 1}."
            out.append(f"  {mark} {names.get(uid, f'#{uid}')} — {cnt}")
        return out

    loser_pairs = sorted(loser_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    chukhan_pairs = [(int(uid), int(cnt)) for uid, cnt in chukhan_rows]
    lines = (
        ["🏆 <b>Топы за всё время</b>", ""]
        + _block("💩 Чуханы недели", chukhan_pairs, "пока никого")
        + [""]
        + _block("👑 Лохи дня", loser_pairs, "пока никого")
    )
    await message.answer("\n".join(lines), parse_mode="HTML")


# ---------------------- C4: /tasks ----------------------

# Дублируем словарь меток из routes_admin, чтобы не тащить FastAPI-роутер в импортах.
_JOB_LABELS: dict[str, str] = {
    "chukhan_weekly": "💩 Чухан недели",
    "meeting_reminders_tick": "⏰ Тик напоминаний",
    "avatar_sync_daily": "🖼️ Синхронизация аватарок",
    "random_phrases": "💬 Автопост рандомных фраз",
    "autoloser": "🤡 Автолох",
    "birthdays_daily": "🎂 Дни рождения",
}


@router.message(Command("tasks"))
async def on_tasks(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return
    from app.bot.scheduler import get_scheduler

    settings = get_settings()
    tz = ZoneInfo(settings.scheduler_tz)
    sched = get_scheduler()
    jobs = list(sched.get_jobs())
    if not jobs:
        await message.answer("🕳️ Запланированных задач нет.")
        return

    rows: list[tuple[datetime | None, str]] = []
    for j in jobs:
        # Скрываем «extra»-fixed-times, чтобы не засорять выдачу
        if j.id.startswith("random_phrases:extra:"):
            continue
        label = _JOB_LABELS.get(j.id, j.id)
        nxt = j.next_run_time
        rows.append((nxt, label))

    rows.sort(key=lambda r: (r[0] is None, r[0] or datetime.max.replace(tzinfo=timezone.utc)))

    lines = ["📋 <b>Запланированные задачи:</b>", ""]
    now = datetime.now(timezone.utc)
    for nxt, label in rows:
        if nxt is None:
            lines.append(f"• {label} — <i>не запланировано</i>")
            continue
        local = nxt.astimezone(tz).strftime("%a %d.%m %H:%M")
        delta = nxt - now
        eta = _humanize_delta(delta)
        lines.append(f"• {label} — {local} <i>({eta})</i>")

    await message.answer("\n".join(lines))


# ---------------------- E6: /nominate (+legacy /nominate_game) и /remove_nominated_game ----------------------

# G1: команда переименована /nominate_game → /nominate; старая остаётся alias'ом
# через `commands=[...]`, чтобы привычные вызовы не ломались. Ack-сообщение
# теперь содержит текущий список (см. ниже).

@router.message(Command(commands=["nominate", "nominate_game"]))
async def on_nominate_game(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return
    if not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "🎮 Использование: <code>/nominate Название игры</code>",
            parse_mode="HTML",
        )
        return
    name = parts[1].strip()

    from app.services.games import (
        MAX_ACTIVE_NOMINATIONS,
        NominationEmpty,
        NominationLimitExceeded,
        add_nomination,
        list_active_nominations,
    )

    sm = get_sessionmaker()
    async with sm() as session:
        # Pre-snapshot чтобы понять статус (created / restored / already)
        # без инвазивных правок сервиса. id-set'ы пересечём — три состояния
        # покрываются однозначно.
        before = await list_active_nominations(session)
        before_ids = {r.id for r in before}
        norm_target = name.strip().lower()
        already_active = any(r.name.strip().lower() == norm_target for r in before)

        try:
            row = await add_nomination(
                session, name=name, added_by_tg_id=message.from_user.id
            )
        except NominationEmpty:
            await message.answer("⚠️ Имя не может быть пустым.")
            return
        except NominationLimitExceeded:
            await message.answer(
                f"⚠️ Уже {MAX_ACTIVE_NOMINATIONS} активных номинаций — "
                f"сначала удали лишние через <code>/remove_nominated_game</code>.",
                parse_mode="HTML",
            )
            return

        after = await list_active_nominations(session)

    if already_active:
        status_line = f"ℹ️ <b>{row.name}</b> уже в списке номинаций"
    elif row.id in before_ids:
        # маловероятно (active=False но id остался) — на всякий случай
        status_line = f"🎮 <b>{row.name}</b> уже в списке номинаций"
    else:
        # Свежая или восстановлена из soft-delete — в обоих случаях для
        # пользователя это «появилась в активных».
        # Различаем по before_ids: если id новый — created/restored.
        restored = any(r.id == row.id for r in before) is False and len(after) <= len(before) + 1
        # Простое сообщение: «добавлена». «Возвращена» — только если была удалена
        # ранее (id присутствовал в БД до вызова — определить дёшево не можем без
        # отдельного запроса, опускаем тонкость).
        _ = restored
        status_line = f"🎮 <b>{row.name}</b> добавлена в номинации"

    total = len(after)
    header = f"{status_line} ({total}/{MAX_ACTIVE_NOMINATIONS})"
    if after:
        names = ", ".join(f"<b>{r.name}</b>" for r in after)
        body = f"\nТекущий список: {names}"
    else:
        body = ""
    await message.answer(header + body, parse_mode="HTML")


@router.message(Command(commands=["remove_nominated_game", "remove_nominated"]))
async def on_remove_nominated_game(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return
    if not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "🗑 Использование: <code>/remove_nominated_game Название игры</code>",
            parse_mode="HTML",
        )
        return
    name = parts[1].strip()

    from app.services.games import remove_nomination_by_name

    sm = get_sessionmaker()
    async with sm() as session:
        row = await remove_nomination_by_name(session, name=name)
    if row is None:
        await message.answer("⚠️ Не нашёл такую игру в активных номинациях.")
        return
    await message.answer(f"🗑 Удалено: <b>{row.name}</b>", parse_mode="HTML")


def _humanize_delta(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 0:
        return "скоро"
    if total < 60:
        return f"{total} c"
    if total < 3600:
        return f"{total // 60} мин"
    if total < 86400:
        h = total // 3600
        return f"{h} ч"
    d = total // 86400
    return f"{d} дн"
