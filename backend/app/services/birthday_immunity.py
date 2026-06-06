"""GHG8 P3: иммунитет именинника к лоху/чухану.

В день рождения участник не может стать «лохом дня»/«автолохом»/«чуханом
недели». Два режима подачи (admin_config `birthdays.immunity_mode`):

- ``announce`` (default) — именинник участвует в рулетке, но при выпадении
  вызывающий код оглашает «мог бы стать %name%, но у него ДР», ждёт 1–2с и
  рероллит. В БД/историю/календарь «черновая» попытка НЕ пишется.
- ``silent`` — именинник исключается из пула кандидатов до броска.

Чистая логика отделена от I/O: `birthday_user_ids_today` — один SELECT по
таблице `birthdays` (сравнение день+месяц, как в titles_current), решение —
`resolve_immune_pick` (чистая функция, легко тестировать; кейс «2 именинника
в один день» — оба в immune_ids).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Birthday, User
from app.services.admin_config import get_birthdays_immunity_mode

# Задержка между оглашением «мог бы стать…» и рероллом (спека: 1–2с).
ANNOUNCE_REROLL_DELAY_SEC = 1.5

# Сколько раз позволяем рероллить в announce-режиме прежде чем сдаться и
# выбрать не-именинника напрямую. Страховка от вырожденного пула (все 6 —
# именинники): без лимита цикл бесконечен, с лимитом — детерминированный выход.
MAX_ANNOUNCE_REROLLS = 10


async def birthday_user_ids_today(
    session: AsyncSession, today: date | None = None
) -> set[int]:
    """user_id всех, у кого сегодня ДР (UTC, сравнение день+месяц —
    зеркало titles_current в routes_calendar.py)."""
    t = today or datetime.now(timezone.utc).date()
    rows = (
        await session.scalars(select(Birthday).where(Birthday.bday.is_not(None)))
    ).all()
    return {
        b.user_id
        for b in rows
        if b.bday is not None and b.bday.month == t.month and b.bday.day == t.day
    }


@dataclass
class ImmunePick:
    """Результат выбора с учётом иммунитета.

    - `user` — финальный кандидат (не именинник, если был кто-то ещё).
    - `skipped_names` — display_name именинников, выпадавших до финального
      кандидата (announce-режим; пустой список в silent или если иммунитет
      не сработал). Вызывающий код оглашает их с задержкой
      ANNOUNCE_REROLL_DELAY_SEC перед публикацией финального поста.
    """

    user: User
    skipped_names: list[str]


def resolve_immune_pick(
    users: list[User],
    immune_ids: set[int],
    mode: str,
    pick_fn,
) -> ImmunePick:
    """Выбрать кандидата с учётом иммунитета. Чистая функция (random — через
    pick_fn, в тестах подменяется детерминированным).

    `pick_fn(candidates: list[User]) -> User` — стратегия выбора (равновесный
    random.choice у лоха, взвешенный _pick_weighted у чухана).

    - mode='silent': именинники выкидываются из пула ДО выбора. Если после
      фильтра пусто (все именинники) — иммунитет игнорируется (кто-то должен
      выпасть; вырожденный кейс «вся шестёрка в один день» нереален, но не падаем).
    - mode='announce': выбираем по полному пулу; именинник → в skipped_names
      и реролл по пулу БЕЗ именинников (двух оглашений одного имени не будет —
      каждый skipped попадает в список один раз, т.к. дальше пул чистый).
    """
    if not users:
        raise RuntimeError("no users to pick from")

    non_immune = [u for u in users if u.id not in immune_ids]
    if not non_immune:
        # Все — именинники: иммунитет невозможен, выбираем по полному пулу.
        return ImmunePick(user=pick_fn(users), skipped_names=[])

    if mode == "silent":
        return ImmunePick(user=pick_fn(non_immune), skipped_names=[])

    # announce: честный бросок по полному пулу, чтобы «мог бы стать…»
    # реально случался с шансом именинника.
    skipped: list[str] = []
    candidate = pick_fn(users)
    rerolls = 0
    while candidate.id in immune_ids and rerolls < MAX_ANNOUNCE_REROLLS:
        skipped.append(candidate.display_name)
        candidate = pick_fn(non_immune)
        rerolls += 1
    if candidate.id in immune_ids:  # страховка, по построению недостижимо
        candidate = random.choice(non_immune)
    return ImmunePick(user=candidate, skipped_names=skipped)


async def immune_pick(
    session: AsyncSession,
    users: list[User],
    pick_fn,
    today: date | None = None,
) -> ImmunePick:
    """I/O-обёртка: читает режим и список именинников, зовёт resolve_immune_pick."""
    immune_ids = await birthday_user_ids_today(session, today)
    if not immune_ids:
        return ImmunePick(user=pick_fn(users), skipped_names=[])
    mode = await get_birthdays_immunity_mode(session)
    return resolve_immune_pick(users, immune_ids, mode, pick_fn)


def format_immunity_announce(skipped_name: str) -> str:
    """Текст оглашения «мог бы стать, но ДР» (один на каждого skipped)."""
    return (
        f"🎂 Мог бы стать <b>{skipped_name}</b>, но у него сегодня день "
        f"рождения — иммунитет. Крутим заново…"
    )


async def announce_immunity_skips(
    bot,
    chat_id: int,
    skipped_names: list[str],
    *,
    send_timeout: float = 25.0,
) -> None:
    """Огласить «черновых» именинников ПЕРЕД основным постом ролла.

    Best-effort: фейл отправки оглашения не должен ронять основной пост —
    логируем и продолжаем. После каждого оглашения — пауза
    ANNOUNCE_REROLL_DELAY_SEC (спека: реролл «с небольшой задержкой»).
    """
    import asyncio

    import structlog

    log = structlog.get_logger()
    for name in skipped_names:
        try:
            await asyncio.wait_for(
                bot.send_message(
                    chat_id=chat_id,
                    text=format_immunity_announce(name),
                    parse_mode="HTML",
                ),
                timeout=send_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("immunity.announce_failed", name=name, error=str(exc))
        await asyncio.sleep(ANNOUNCE_REROLL_DELAY_SEC)
