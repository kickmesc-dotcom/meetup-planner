"""GHG10 Э11: донат опыта имениннику.

Задание: «каждому участнику в ДР, если кликнуть на тортик, отдельной кнопкой
можно задонатить 100 очков экспы, но буквально вычев их из своих. Донатить можно
только один раз в году каждому участнику (чтобы не абьюзили, тупо двигая даты
др-шек). Делать можно только в непосредственный день рождения согласно
сохранённой дате. Если у тебя самого 0 очков, то и донатить нечего (можно
высмеять в чат такую наивную попытку)».

Четыре правила задания — четыре проверки в `donate`, и все они стоят ДО записи:

1. **сам себе не донатишь** — иначе это вечный двигатель опыта;
2. **только в сам день ДР** по сохранённой дате (`birthdays.bday`, месяц+день):
   двигать дату, чтобы прокачаться, не выйдет — она лежит в профиле юзера и
   правится не им;
3. **раз в году на получателя** — маркер в `xp_grants`
   (`donation_sent:all:<получатель>:<год>`): ключ тот же, что у окон начисления,
   поэтому «абьюз датами» упирается в календарь, а не в счётчик в памяти;
4. **свои очки должны быть** — `DONATION_AMOUNT` списывается переводом, а не
   выдаётся из воздуха (общий счёт опыта в системе не растёт).

Перевод — ДВЕ записи опыта в одной транзакции: донор теряет, именинник
приобретает. Ачивки («Кэшбэк», «Дон Королеве») — уже ПОСЛЕ commit'а: их падение
не имеет права откатить сам перевод (то же правило, что у остальных событий).

ГОНКА (двойной тап по кнопке в мини-аппе): запросы читают «ещё не донатил»
одновременно, а уникальный индекс `xp_grants` пропускает только один маркер.
Проигравший ловит `IntegrityError` и отдаёт `ALREADY_DONATED`, а не 500:
благодаря одной транзакции откатывается ВЕСЬ перевод, так что расхождение
балансов невозможно, и опыт не задваивается.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Birthday, User, XpGrant
from app.services.game import awards, xp
from app.services.game.config import (
    DONATION_AMOUNT,
    EV_DONATION_RECEIVED,
    EV_DONATION_SENT,
)
from app.services.game.flags import is_game_enabled

log = structlog.get_logger()

# Коды результата: уезжают в API как `detail` (фронт переводит их сам).
OK = "ok"
SELF_DONATION = "self_donation"
NOT_BIRTHDAY = "not_today_birthday"
ALREADY_DONATED = "already_donated"
NOT_ENOUGH_XP = "not_enough_xp"

# Префикс маркеров доната в `xp_grants` (`donation_sent:all:<to>:<year>`).
_SENT_PREFIX = "donation_sent:all:"

# Насмешки за попытку подарить то, чего нет. Чистая функция возвращает готовый
# текст — в БД/API его не тащим, он нужен только чату.
TEASING_TEMPLATES = (
    "🍑 <b>{name}</b> решил подарить опыт, которого у самого нет. "
    "0 XP — такой же подарок, как носки на ДР.",
    "🫙 <b>{name}</b> замахнулся на щедрость, но кошелёк пуст: 0 XP. "
    "Донат от нищего — это уже искусство.",
    "💸 <b>{name}</b> попытался задонатить {amount} XP, имея {xp}. "
    "Пересчитай ещё раз, меценат.",
)


@dataclass(frozen=True)
class DonationResult:
    """Итог попытки: код + балансы (для UI и тестов)."""

    code: str
    ok: bool = False
    amount: int = 0
    donor_xp: int = 0
    recipient_xp: int = 0
    recipients_this_year: int = 0
    live_participants: int = 0


def marker_key(recipient_id: int, year: int) -> str:
    """Ключ маркера «донор → получатель в этом году». Чистая (тесты)."""
    return f"{_SENT_PREFIX}{recipient_id}:{year}"


def sent_prefix_for_year(year: int) -> str:
    """Префикс всех донатов года (для COUNT «скольким уже подарил»)."""
    return f"{_SENT_PREFIX}%:{year}"


def teasing_message(name: str, *, xp_now: int, variant: int = 0) -> str:
    """Насмешка над донатом с нулевым балансом. Чистая функция."""
    template = TEASING_TEMPLATES[variant % len(TEASING_TEMPLATES)]
    return template.format(name=name, xp=xp_now, amount=DONATION_AMOUNT)


async def _birthday_today(session: AsyncSession, user_id: int, today: date) -> bool:
    """ДР по СОХРАНЁННОЙ дате (месяц+день) — как в `birthday_immunity`."""
    bday = await session.scalar(
        select(Birthday.bday).where(Birthday.user_id == user_id)
    )
    return bday is not None and bday.month == today.month and bday.day == today.day


async def donate(
    session: AsyncSession,
    *,
    donor_id: int,
    recipient_id: int,
    at: datetime | None = None,
) -> DonationResult:
    """Перевести `DONATION_AMOUNT` XP от донора имениннику.

    Возвращает код отказа без исключений: вызывающий код (роут/бот) сам решает,
    что показать — 400, 409 или насмешку в чат.
    """
    if not await is_game_enabled(session):
        return DonationResult(code="game_disabled")
    if donor_id == recipient_id:
        return DonationResult(code=SELF_DONATION)

    moment = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not await _birthday_today(session, recipient_id, moment.date()):
        return DonationResult(code=NOT_BIRTHDAY)

    key = marker_key(recipient_id, moment.year)
    already = await session.scalar(
        select(func.count())
        .select_from(XpGrant)
        .where(XpGrant.user_id == donor_id, XpGrant.idem_key == key)
    )
    if already:
        return DonationResult(code=ALREADY_DONATED)

    donor_xp = await xp.get_xp(session, donor_id)
    if donor_xp < DONATION_AMOUNT:
        return DonationResult(
            code=NOT_ENOUGH_XP, amount=DONATION_AMOUNT, donor_xp=donor_xp
        )

    # Перевод: донор теряет, именинник приобретает — ОДНА транзакция (первый
    # award только flush'ит, коммит делает второй). Порядок важен: если упадёт
    # второе начисление, списание откатится вместе с ним.
    try:
        await xp.award(
            session,
            donor_id,
            EV_DONATION_SENT,
            at=moment,
            points=-DONATION_AMOUNT,
            discriminator=f"{recipient_id}:{moment.year}",
            commit=False,
        )
        await xp.award(
            session,
            recipient_id,
            EV_DONATION_RECEIVED,
            at=moment,
            points=DONATION_AMOUNT,
            discriminator=donor_id,
        )
    except IntegrityError:
        # Прогон проиграл гонку: маркер уже занят параллельным запросом. Опыт
        # ещё не уехал (транзакция одна) — откатываем и отвечаем так же, как на
        # обычный повтор. Без этой ветки двойной тап в мини-аппе давал бы 500.
        await session.rollback()
        log.info(
            "game.donation_race_lost",
            donor_id=donor_id,
            recipient_id=recipient_id,
        )
        return DonationResult(code=ALREADY_DONATED)

    recipients = int(
        await session.scalar(
            select(func.count())
            .select_from(XpGrant)
            .where(
                XpGrant.user_id == donor_id,
                XpGrant.idem_key.like(sent_prefix_for_year(moment.year)),
            )
        )
        or 0
    )
    live = int(await session.scalar(select(func.count()).select_from(User)) or 0)

    log.info(
        "game.donation_sent",
        donor_id=donor_id,
        recipient_id=recipient_id,
        amount=DONATION_AMOUNT,
        recipients_this_year=recipients,
    )

    # Ачивки — после commit'а перевода (см. докстринг модуля).
    await awards.donation_sent(
        session,
        donor_id,
        recipients_this_year=recipients,
        live_participants=live,
    )

    return DonationResult(
        code=OK,
        ok=True,
        amount=DONATION_AMOUNT,
        donor_xp=await xp.get_xp(session, donor_id),
        recipient_xp=await xp.get_xp(session, recipient_id),
        recipients_this_year=recipients,
        live_participants=live,
    )
