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

GHG10 Э9: сюда же приходят ЧУЖИЕ причины иммунитета (пожизненные за 9/10 ранг
— `services/game/immunity.py`) через параметр `reasons`. Модуль остался
единственной точкой броска с учётом иммунитета: логика выбора и оглашения не
дублируется на игру, а причина лишь описывается данными (`services/immunity.py`).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Birthday, User
from app.services.admin_config import get_birthdays_immunity_mode
from app.services.immunity import BIRTHDAY_REASON, ImmuneReason, ImmuneSkip

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

    - `user` — финальный кандидат (не иммунный, если был кто-то ещё).
    - `skipped` — оглашаемые «черновые» кандидаты с причиной (announce-режим;
      пустой список в silent или если иммунитет не сработал). Вызывающий код
      оглашает их с задержкой ANNOUNCE_REROLL_DELAY_SEC перед публикацией
      финального поста.
    - `skipped_names` — те же имена списком (совместимость и логи/тесты).
    """

    user: User
    skipped: list[ImmuneSkip] = field(default_factory=list)

    @property
    def skipped_names(self) -> list[str]:
        return [s.name for s in self.skipped]


def resolve_immune_pick(
    users: list[User],
    immune_ids: set[int],
    mode: str,
    pick_fn,
    reasons: dict[int, ImmuneReason] | None = None,
) -> ImmunePick:
    """Выбрать кандидата с учётом иммунитета. Чистая функция (random — через
    pick_fn, в тестах подменяется детерминированным).

    `pick_fn(candidates: list[User]) -> User` — стратегия выбора (равновесный
    random.choice у лоха, взвешенный _pick_weighted у чухана).

    `reasons` — почему конкретный id неприкосновенен (нужно только для текста
    оглашения). Для id без записи считается причиной день рождения: исторически
    это единственный вид иммунитета, и так текст GHG8 не меняется.

    - mode='silent': иммунные выкидываются из пула ДО выбора. Если после
      фильтра пусто (все иммунные) — иммунитет игнорируется (кто-то должен
      выпасть; вырожденный кейс «вся шестёрка разом» нереален, но не падаем).
    - mode='announce': выбираем по полному пулу; иммунный → в skipped
      и реролл по пулу БЕЗ иммунных (двух оглашений одного имени не будет —
      каждый skipped попадает в список один раз, т.к. дальше пул чистый).
    """
    if not users:
        raise RuntimeError("no users to pick from")

    non_immune = [u for u in users if u.id not in immune_ids]
    if not non_immune:
        # Все иммунные: иммунитет невозможен, выбираем по полному пулу.
        return ImmunePick(user=pick_fn(users))

    if mode == "silent":
        return ImmunePick(user=pick_fn(non_immune))

    def _skip(user: User) -> ImmuneSkip:
        reason = (reasons or {}).get(user.id) or BIRTHDAY_REASON
        return ImmuneSkip(user_id=user.id, name=user.display_name, reason=reason)

    # announce: честный бросок по полному пулу, чтобы «мог бы стать…»
    # реально случался с шансом иммунного.
    skipped: list[ImmuneSkip] = []
    candidate = pick_fn(users)
    rerolls = 0
    while candidate.id in immune_ids and rerolls < MAX_ANNOUNCE_REROLLS:
        skipped.append(_skip(candidate))
        candidate = pick_fn(non_immune)
        rerolls += 1
    if candidate.id in immune_ids:  # страховка, по построению недостижимо
        candidate = random.choice(non_immune)
    return ImmunePick(user=candidate, skipped=skipped)


async def immune_pick(
    session: AsyncSession,
    users: list[User],
    pick_fn,
    today: date | None = None,
    reasons: dict[int, ImmuneReason] | None = None,
) -> ImmunePick:
    """I/O-обёртка: читает режим и иммунных, зовёт resolve_immune_pick.

    `reasons` — дополнительные причины иммунитета помимо дня рождения (Э9:
    пожизненные за ранги). Режим (announce/silent) общий для всех видов
    иммунитета: в чате не должно быть двух разных стилей оглашения.
    """
    extra = dict(reasons or {})
    immune_ids = await birthday_user_ids_today(session, today) | set(extra)
    if not immune_ids:
        return ImmunePick(user=pick_fn(users))
    mode = await get_birthdays_immunity_mode(session)
    return resolve_immune_pick(users, immune_ids, mode, pick_fn, reasons=extra)


def format_immunity_announce(skipped_name: str) -> str:
    """Текст оглашения «мог бы стать, но ДР» (один на каждого skipped)."""
    return BIRTHDAY_REASON.text(skipped_name)


async def announce_immunity_skips(
    bot,
    chat_id: int,
    skipped: list[ImmuneSkip],
    *,
    send_timeout: float = 25.0,
) -> None:
    """Огласить «черновых» кандидатов ПЕРЕД основным постом ролла.

    Текст берём у самого скипа (`ImmuneSkip.text`) — он уже зависит от причины
    (ДР, ранг 9/10), поэтому модуль не знает, за что именно иммунитет.

    Best-effort: фейл отправки оглашения не должен ронять основной пост —
    логируем и продолжаем. После каждого оглашения — пауза
    ANNOUNCE_REROLL_DELAY_SEC (спека: реролл «с небольшой задержкой»).
    """
    import asyncio

    import structlog

    log = structlog.get_logger()
    for skip in skipped:
        try:
            await asyncio.wait_for(
                bot.send_message(
                    chat_id=chat_id,
                    text=skip.text,
                    parse_mode="HTML",
                ),
                timeout=send_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "immunity.announce_failed",
                name=skip.name,
                reason=skip.reason.code,
                error=str(exc),
            )
        await asyncio.sleep(ANNOUNCE_REROLL_DELAY_SEC)
