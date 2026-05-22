from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LoserRoll, User, WormAssignment
from app.services.admin_config import (
    get_loser_reasons,
    get_worm_chance,
    is_worm_enabled,
)
from app.services.phrase_weights import (
    LOSER_USE_COUNTS_KEY,
    get_use_counts,
    increment_use_count,
    weighted_choice,
)


WORM_REASON_TEXT = "Особая номинация: Червь-пидор"


@dataclass
class WormEvent:
    """Дополнительная информация о выпадении «червя-пидора» при roll_loser.

    Передаётся в `on_announce` как третий позиционный аргумент. Если червь
    не выпал — `triggered=False`, остальные поля игнорируются.
    """
    triggered: bool = False
    prev_worm_name: str | None = None  # display_name предыдущего червя, если был
    chance_used: float = 0.0


@dataclass
class RollExtras:
    """Контейнер «лишних» сведений о ролле для `on_announce`. Расширяемый —
    в будущем сюда могут попасть, например, «лох недели/месяца»-хайлайты."""
    worm: WormEvent = field(default_factory=WormEvent)

COOLDOWN = timedelta(hours=12)

LOSER_REASONS = [
    "слился с последней встречи",
    "неделю не заходил в чат",
    "тусуется с левыми типами",
    "выбирает семью",
    "воняет говной",
    "дохера умничает",
    "кидает протухшие мемы",
    "его реакции — это просто 👌",
    "ушёл в себя на неделю",
    "снова ставит \"под вопросом\"",
    "не признает, кто здесь батя",
    "всплывает только когда ему что-то надо",
    "вечно ноет",
    "сидит онлайн и молчит как труп",
    "слишком занят своей важной жопой",
    "не выкупает рофлы",
    "не выкупает за метаиронию",
    "опять не выпил таблетки",
    "путает чат с доской объявлений",
    "забыл дорогу в конфу",
    "снова пропал без вести",
    "ведёт себя как NPC",
    "отвечает раз в трое суток",
    "как обычно дал заднюю",
    "пришёл, увидел, обосрался",
    "ссыт нормального движняка",
    "вечно на серьёзных щах",
    "мутит мутные схемы",
    "потерялся между диваном и кухней",
    "ждёт особого приглашения как принцесса",
    "его юмор умер в 2017",
    "вечно в режиме энергосбережения",
    "опять включил режим призрака",
    "разболталось гнездо",
    "сидит на морозе как неродной",
    "воюет не в ту сторону",
    "обитает где-то между кринжем и позором",
    "общается как будто делает одолжение",
    "давно не трогал траву",
    "строит из себя занятого миллиардера",
    "тонет в своей драме",
    "выходит на связь только по праздникам",
    "путает дружбу с подпиской",
    "слишком нестабилен даже для мемов",
    "маячит, аки говно в проруби",
]


async def time_until_next_roll(session: AsyncSession) -> timedelta:
    last = await session.scalar(select(func.max(LoserRoll.rolled_at)))
    if last is None:
        return timedelta(0)
    elapsed = datetime.now(timezone.utc) - last
    remaining = COOLDOWN - elapsed
    return max(timedelta(0), remaining)


AnnounceFn = Callable[..., Awaitable[None]]


async def roll_loser(
    session: AsyncSession,
    *,
    rolled_by: User,
    on_announce: AnnounceFn | None = None,
) -> LoserRoll:
    """Roll a loser atomically with the chat announcement.

    If `on_announce` is provided, it's invoked AFTER flushing the row but
    BEFORE commit. If it raises, the transaction is rolled back so the
    roll can be retried — no «phantom» DB row without a TG message.

    E8 (GHG6): с шансом `admin_config["worm.chance"]` (default 0.01) выпадает
    «червь-пидор». В этом случае `LoserRoll.reason_text` = `WORM_REASON_TEXT`
    (не случайная фраза из пула), плюс атомарно обновляется таблица
    `worm_assignments`: предыдущая активная запись получает `ended_at=now()`,
    создаётся новая для выбранного юзера. Сигнатура `on_announce` расширена:
    третий аргумент — `RollExtras` с `worm: WormEvent`. Callers, которые
    игнорируют третий аргумент, должны принять `*_` — иначе TypeError на raise.
    """
    remaining = await time_until_next_roll(session)
    if remaining > timedelta(0):
        raise CooldownError(remaining)

    users = list((await session.scalars(select(User))).all())
    if not users:
        raise RuntimeError("no users in DB")

    loser = random.choice(users)

    # E8: бросаем «червь-пидор»
    worm_enabled = await is_worm_enabled(session)
    worm_chance = await get_worm_chance(session) if worm_enabled else 0.0
    is_worm = decide_worm(
        enabled=worm_enabled, chance=worm_chance, rng_value=random.random()
    )

    if is_worm:
        reason = WORM_REASON_TEXT
    else:
        # Берём актуальный список из admin_config (с фолбэком на in-code LOSER_REASONS).
        reasons = await get_loser_reasons(session)
        pool = reasons or list(LOSER_REASONS)
        # GHG6 E5: взвешенный выбор — вес 1/(1+use_count). Свежие фразы чаще,
        # но «нулевого приоритета» нет: уже-использованные всё равно могут
        # выпасть, просто реже.
        use_counts = await get_use_counts(session, LOSER_USE_COUNTS_KEY)
        reason = weighted_choice(pool, use_counts) or random.choice(pool)
        # Инкремент счётчика делаем здесь, до flush — попадает в ту же
        # транзакцию, что и сам ролл, и откатывается вместе с ним если
        # `on_announce` упадёт (для червя — другая ветка, там reason
        # фиксирован, счётчик трогать незачем).
        await increment_use_count(session, LOSER_USE_COUNTS_KEY, reason)

    row = LoserRoll(
        rolled_by=rolled_by.id,
        loser_user_id=loser.id,
        reason_text=reason,
    )
    session.add(row)
    await session.flush()  # populate row.id without committing

    # E8: если выпал червь — закрываем старую активную запись (если была)
    # и создаём новую. Делаем это ДО announce, чтобы откат транзакции при
    # ошибке отправки в TG откатывал и переход звания тоже.
    worm_event = WormEvent(chance_used=worm_chance)
    if is_worm:
        prev_worm = await session.scalar(
            select(WormAssignment).where(WormAssignment.ended_at.is_(None))
        )
        if prev_worm is not None:
            # Имя «бывшего червя» — для текста announce.
            prev_user = await session.get(User, prev_worm.user_id)
            worm_event.prev_worm_name = (
                prev_user.display_name if prev_user else None
            )
            # Не помечаем как «бывший червь = новый», если это тот же юзер
            # (червь повторно выпал тому же лицу). В этом случае —
            # продлеваем, не закрывая → не создаём новую строку.
            if prev_worm.user_id == loser.id:
                # Уже был червём — просто оставляем активную запись.
                worm_event.triggered = True
                if on_announce is not None:
                    try:
                        await on_announce(row, loser, RollExtras(worm=worm_event))
                    except Exception:
                        await session.rollback()
                        raise
                await session.commit()
                await session.refresh(row)
                return row
            prev_worm.ended_at = datetime.now(timezone.utc)
            await session.flush()
        session.add(
            WormAssignment(
                user_id=loser.id,
                source_loser_roll_id=row.id,
            )
        )
        await session.flush()
        worm_event.triggered = True

    extras = RollExtras(worm=worm_event)

    if on_announce is not None:
        try:
            await on_announce(row, loser, extras)
        except Exception:
            await session.rollback()
            raise

    await session.commit()
    await session.refresh(row)
    return row


async def get_current_worm(session: AsyncSession) -> WormAssignment | None:
    """Активный червь-пидор (≤1 строки с ended_at IS NULL). None если нет."""
    return await session.scalar(
        select(WormAssignment).where(WormAssignment.ended_at.is_(None))
    )


def decide_worm(*, enabled: bool, chance: float, rng_value: float) -> bool:
    """Чистая функция: выпадает ли «червь-пидор»?

    `rng_value` — число из `random.random()` (0 ≤ v < 1). Триггер: enabled AND
    chance > 0 AND rng_value < chance. Шанс ≤0 — никогда; ≥1 — всегда (clamp
    хранится при записи, здесь только сравнение). Возвращает bool.
    """
    if not enabled or chance <= 0.0:
        return False
    return rng_value < chance


def compose_loser_message(
    *,
    loser_name: str,
    reason_text: str,
    roller_name: str | None = None,
    loser_count: int | None = None,
    extras: RollExtras | None = None,
    header_emoji: str = "🎲",
    header_label: str = "Лох дня",
) -> str:
    """Единый шаблон HTML-сообщения о ролле лоха. Используется всеми callers
    (`routes_meetings.loser_roll`, `routes_admin.admin_loser_roll_now`,
    scheduler autoloser, chat_commands `/loser`).

    При выпадении «червя-пидора» (`extras.worm.triggered=True`) шаблон
    переключается на яркую форму: bold-хедер 🚨 ОСОБАЯ НОМИНАЦИЯ, имя
    выделено крупно, добавляется блок передачи звания (если был
    предыдущий носитель). Сами по себе reasons из пула — в этом сообщении
    не печатаются, потому что `reason_text` уже подменён на
    `WORM_REASON_TEXT`.
    """
    is_worm = bool(extras and extras.worm.triggered)

    if is_worm:
        lines = [
            "🚨 <b>ОСОБАЯ НОМИНАЦИЯ</b> 🚨",
            "",
            f"🪱 <b>{loser_name}</b> — ты <b>ЧЕРВЬ-ПИДОР</b>!",
            "",
            "Это редчайшее звание. Носи с честью (или с позором).",
        ]
        prev = extras.worm.prev_worm_name if extras else None
        if prev and prev != loser_name:
            lines.append("")
            lines.append(
                f"<i>Старый червь «{prev}» слагает полномочия. "
                f"Корона переходит.</i>"
            )
        if roller_name:
            lines.append("")
            lines.append(f"<i>Покрутил рулетку: {roller_name}</i>")
        # Лох-счётчик прибавляется тоже — пишем мелко, чтобы не отвлекать
        # от основного эффекта.
        if loser_count is not None:
            lines.append(f"<i>(Заодно {loser_count}-й раз становится лохом.)</i>")
        return "\n".join(lines)

    # Обычный лох
    lines = [f"{header_emoji} <b>{header_label}</b> — {loser_name}!"]
    if reason_text:
        lines.append(f"Причина: {reason_text}")
    if loser_count is not None:
        lines.append(f"Уже {loser_count}-й раз становится лохом.")
    if roller_name:
        lines.append(f"<i>Покрутил рулетку: {roller_name}</i>")
    return "\n".join(lines)


async def delete_last_loser(session: AsyncSession) -> LoserRoll | None:
    """Drop the most recent loser roll (for manual re-roll). Returns the
    deleted row or None if there was nothing to delete."""
    row = await session.scalar(
        select(LoserRoll).order_by(desc(LoserRoll.rolled_at)).limit(1)
    )
    if row is None:
        return None
    await session.delete(row)
    await session.commit()
    return row


async def loser_stats(session: AsyncSession) -> dict[int, int]:
    rows = (
        await session.execute(
            select(LoserRoll.loser_user_id, func.count())
            .group_by(LoserRoll.loser_user_id)
        )
    ).all()
    return {uid: int(cnt) for uid, cnt in rows}


async def last_loser(session: AsyncSession) -> LoserRoll | None:
    return await session.scalar(select(LoserRoll).order_by(desc(LoserRoll.rolled_at)).limit(1))


class CooldownError(Exception):
    def __init__(self, remaining: timedelta):
        self.remaining = remaining
        super().__init__(f"cooldown {remaining}")
