"""GHG10: движок начисления опыта.

Единственная точка, через которую опыт попадает в профиль. Всё остальное
(сообщения, лохи, чуханы, ачивки, календарь, праздники, донаты) зовёт `award`.

Два инварианта:

1. **`xp` — источник правды.** Уровень/ранг/престиж не хранятся, а выводятся
   (`levels.py`), поэтому правка баланса в `config.py` не требует миграции и не
   оставляет «застрявших» уровней.
2. **Идемпотентность через окно** (`config.XpRule.limit`). «Разметил календарь»
   даёт опыт раз в неделю, «день рождения» — раз в год, и т.д. Повтор в том же
   окне молча не начисляется (`AwardResult.awarded is False`), а не падает.

Про конкурентность: апдейт — read-modify-write через `session.get`. Для групп
на шестерых это безопасно, но при появлении конкурирующих писателей на одного
юзера (вебхук + планировщик в одну миллисекунду) апгрейд — `INSERT ... ON
CONFLICT DO UPDATE` по образцу остальных сервисов проекта.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameProfile, XpDaily, XpGrant
from app.services.game import levels
from app.services.game.config import (
    XP_RULES,
    Limit,
    limit_for,
    points_for,
)

# Ограничение на длину оконного ключа из-за колонки XpGrant.idem_key (Text —
# без ограничения, но осмысленный предел удобен для чтения в БД).
_MAX_KEY_LEN = 120


def utc_day(at: datetime | None = None) -> date:
    """UTC-сутки. Везде в проекте используется aware UTC — не меняем обычай."""
    return (at or datetime.now(timezone.utc)).astimezone(timezone.utc).date()


def window_key(limit: Limit, at: datetime | None = None) -> str | None:
    """Ключ окна идемпотентности для лимита. `None` — лимита нет.

    ISO-неделя (`2026-W39`) — чтобы «раз в неделю» совпадало с недельным
    календарём/званиями, а не с скользящими 7 днями.
    """
    if limit is None:
        return None
    moment = at or datetime.now(timezone.utc)
    moment = moment.astimezone(timezone.utc)
    if limit == "day":
        return moment.date().isoformat()
    if limit == "week":
        iso = moment.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if limit == "year":
        return str(moment.year)
    if limit == "once":
        return "all"
    # Неизвестный лимит — считаем, что лимита нет (не блокируем начисление).
    return None


def idem_key(
    event: str,
    limit: Limit,
    *,
    at: datetime | None = None,
    discriminator: str | int | None = None,
) -> str | None:
    """Полный ключ идемпотентности события.

    `discriminator` нужен там, где в одном окне возможен не один легальный
    случай: например «инициировал встречу» (лимит `day`) — если за день
    инициировано две встречи, ключ должен отличаться, иначе вторая не
    начислится. Для `limit=None` ключ всегда `None` (лимита нет).
    """
    window = window_key(limit, at)
    if window is None:
        return None
    base = f"{event}:{window}"
    if discriminator is not None:
        base = f"{base}:{discriminator}"
    return base[:_MAX_KEY_LEN]


@dataclass(frozen=True)
class AwardResult:
    """Результат начисления. Вызывающий код решает, анонсировать ли левел-ап."""

    awarded: bool
    points: int
    xp_before: int
    xp_after: int
    levels_gained: tuple[int, ...]
    # Текст причины отказа — для отладки/тестов; в чат не показывается.
    skip_reason: str | None = None


@dataclass(frozen=True)
class DailyBucket:
    """Строка дневной истории: «сообщения ×12 → +12 XP»."""

    event: str
    title: str
    points: int
    count: int


async def get_xp(session: AsyncSession, user_id: int) -> int:
    """Опыт юзера (0, если профиля ещё нет — ленивое создание в `award`)."""
    profile = await session.get(GameProfile, user_id)
    return profile.xp if profile else 0


async def award(
    session: AsyncSession,
    user_id: int,
    event: str,
    *,
    at: datetime | None = None,
    discriminator: str | int | None = None,
    points: int | None = None,
) -> AwardResult:
    """Начислить опыт за событие. Единственный путь появления опыта.

    `points` переопределяет значение из `config` — нужно для ачивок с разной
    ценой и для донатов (там переводится фиксированная сумма, а не «цена
    события»).
    """
    # 1. Лимит окна: повтор в том же окне — не начисляем.
    limit = limit_for(event)
    key = idem_key(event, limit, at=at, discriminator=discriminator)
    if key is not None:
        existing = await session.get(XpGrant, (user_id, key))
        if existing is not None:
            xp_now = await get_xp(session, user_id)
            return AwardResult(
                awarded=False,
                points=0,
                xp_before=xp_now,
                xp_after=xp_now,
                levels_gained=(),
                skip_reason="window-already-granted",
            )

    # 2. Цена события.
    gain = points_for(event) if points is None else points
    if gain == 0:
        # События с нулевой ценой (донат-отправка) существуют только ради
        # маркера окна/статистики — профиль не трогаем.
        if key is not None:
            session.add(XpGrant(user_id=user_id, idem_key=key))
            await session.commit()
        xp_now = await get_xp(session, user_id)
        return AwardResult(
            awarded=True,
            points=0,
            xp_before=xp_now,
            xp_after=xp_now,
            levels_gained=(),
        )

    # 3. Профиль (ленивое создание).
    profile = await session.get(GameProfile, user_id)
    if profile is None:
        profile = GameProfile(user_id=user_id, xp=0)
        session.add(profile)
    xp_before = profile.xp
    xp_after = xp_before + gain
    profile.xp = xp_after

    # 4. Дневная история (агрегат).
    day = utc_day(at)
    bucket = await session.get(XpDaily, (user_id, day, event))
    if bucket is None:
        session.add(
            XpDaily(user_id=user_id, day=day, event=event, points=gain, count=1)
        )
    else:
        bucket.points += gain
        bucket.count += 1

    # 5. Маркер окна.
    if key is not None:
        session.add(XpGrant(user_id=user_id, idem_key=key))

    await session.commit()

    return AwardResult(
        awarded=True,
        points=gain,
        xp_before=xp_before,
        xp_after=xp_after,
        levels_gained=tuple(levels.levels_gained(xp_before, xp_after)),
    )


async def award_many(
    session: AsyncSession,
    user_ids: list[int],
    event: str,
    *,
    at: datetime | None = None,
    points: int | None = None,
) -> list[tuple[int, AwardResult]]:
    """Начислить одно событие сразу нескольким (например праздник — всем).

    Возвращает пары (user_id, результат), чтобы вызывающий код мог анонсировать
    только тех, у кого случился левел-ап.
    """
    out: list[tuple[int, AwardResult]] = []
    for uid in user_ids:
        out.append(
            (uid, await award(session, uid, event, at=at, points=points))
        )
    return out


async def daily_history(
    session: AsyncSession, user_id: int, at: datetime | None = None
) -> list[DailyBucket]:
    """Что и за что начислено СЕГОДНЯ (UTC) — для профиля.

    «В 00-00 история обнуляется» из задания = фильтр по текущим суткам: строки
    прошлых дней не удаляются (агрегат нужен для будущих чартов), просто не
    попадают в выборку.
    """
    day = utc_day(at)
    rows = (
        await session.scalars(
            select(XpDaily)
            .where(XpDaily.user_id == user_id, XpDaily.day == day)
            .order_by(XpDaily.points.desc())
        )
    ).all()
    buckets: list[DailyBucket] = []
    for row in rows:
        rule = XP_RULES.get(row.event)
        buckets.append(
            DailyBucket(
                event=row.event,
                title=rule.title if rule else row.event,
                points=row.points,
                count=row.count,
            )
        )
    return buckets


def total_for_day(buckets: list[DailyBucket]) -> int:
    """Сумма опыта за день (для заголовка истории в профиле)."""
    return sum(b.points for b in buckets)
