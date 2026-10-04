"""Э19: передача прав червя-господина командой в чат — с подтверждением хозяина.

Фидбек оператора:

    «добавим такую фишку как передать бразды правления червём командой в чат
    (при этом бот попросит моментального подтверждения от хозяина, указать здесь
    же он ожидает реплай или среагирует на любой вариант да\\нет в течение
    какого-то периода). По этой команде будет автоматически произведён реролл на
    нового владельца червя.»

Поток:

1. Текущий господин пишет `/worm @кто` (или `/червь`). Бот отвечает просьбой
   подтвердить и запоминает «ожидание» на `DEFAULT_TTL_MINUTES` минут.
2. Господин отвечает «да» или «нет» — реплаем на сообщение-подтверждение или
   просто сообщением (любой вариант). «Да» → автоперолл на нового владельца
   (`loser.assign_worm_to`) и анонс; «нет» → отмена.

Состояние «ожидания» храним в СУЩЕСТВУЮЩЕЙ таблице `event_log` (kind=
`worm_transfer_pending`), без новой таблицы и миграции. Это же место хранит и
единоразовый флаг «инфо-уведомление о фиче уже отправлено» (см. `main.lifespan`),
чтобы после деплоя объявить фичу один раз и никогда не повторяться.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EventLog

log = structlog.get_logger()

# Виды записей в `event_log`.
PENDING_KIND = "worm_transfer_pending"

# Сколько ждём подтверждения. 30 минут — «моментальное» подтверждение: мастер
# увидит просьбу сразу и ответит; за полчаса случайное «да» из болтовни маловероятно.
DEFAULT_TTL_MINUTES = 30

# Разбор «да/нет». Принимаем и слова, и короткие вариации — «среагирует на любой
# вариант». Строку нормализуем (регистр, пунктуация) и сверяем по множествам.
_YES_WORDS = {
    "да",
    "ага",
    "угу",
    "ок",
    "окей",
    "ok",
    "okay",
    "yes",
    "yep",
    "yeah",
    "подтверждаю",
    "передай",
    "передавай",
    "давай",
    "+",
    "++",
}
_NO_WORDS = {
    "нет",
    "не",
    "неа",
    "no",
    "nope",
    "отмена",
    "отставить",
    "отказываюсь",
    "стоп",
    "-",
    "--",
}
_NORMALIZE_RE = re.compile(r"[.!?,;:»«\"']+$")


def parse_confirmation(text: str | None) -> bool | None:
    """«Да» → True, «нет» → False, ничего/непонятно → None. Чистая функция."""
    if not text:
        return None
    token = _NORMALIZE_RE.sub("", text.strip().lower()).strip()
    if token in _YES_WORDS:
        return True
    if token in _NO_WORDS:
        return False
    return None


def _expires_at(payload: dict | None) -> datetime | None:
    raw = (payload or {}).get("expires_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


async def find_open(session: AsyncSession, *, now: datetime | None = None) -> EventLog | None:
    """Незакрытое и не истёкшее ожидание подтверждения. None — если нет.

    Смотрим несколько последних записей: старые либо помечены `resolved`, либо
    уже истекли. Так не держим отдельного индекса и не плодим таблицу.
    """
    moment = now or datetime.now(timezone.utc)
    rows = await session.scalars(
        select(EventLog)
        .where(EventLog.kind == PENDING_KIND)
        .order_by(EventLog.id.desc())
        .limit(10)
    )
    for row in rows.all():
        payload = row.payload or {}
        if payload.get("resolved"):
            continue
        expires = _expires_at(payload)
        if expires is None or expires <= moment:
            continue
        return row
    return None


async def create_pending(
    session: AsyncSession,
    *,
    issuer_id: int,
    target_id: int,
    chat_id: int | None,
    confirm_message_id: int | None,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
    now: datetime | None = None,
) -> EventLog:
    """Запомнить ожидание подтверждения. Возвращает созданную запись журнала."""
    moment = now or datetime.now(timezone.utc)
    entry = EventLog(
        at=moment,
        actor_user_id=issuer_id,
        kind=PENDING_KIND,
        payload={
            "target_user_id": int(target_id),
            "chat_id": chat_id,
            "confirm_message_id": confirm_message_id,
            "expires_at": (moment + timedelta(minutes=ttl_minutes)).isoformat(),
            "resolved": False,
        },
    )
    session.add(entry)
    await session.flush()
    log.info("game.worm_transfer_pending", issuer=issuer_id, target=target_id)
    return entry


async def consume_confirmation(
    session: AsyncSession,
    *,
    author_user_id: int,
    text: str | None,
    chat_id: int | None = None,
    at: datetime | None = None,
) -> tuple[EventLog, bool] | None:
    """Обработать ответ-подтверждение. None — если это не подтверждение.

    Возвращает (ожидание, confirmed). Помечает ожидание resolved (payload
    переприсваиваем — SQLAlchemy видит изменение JSONB).
    """
    pending = await find_open(session, now=at)
    if pending is None:
        return None
    if pending.actor_user_id != author_user_id:
        return None
    payload = pending.payload or {}
    if chat_id is not None and payload.get("chat_id") not in (None, chat_id):
        return None
    confirmed = parse_confirmation(text)
    if confirmed is None:
        return None
    payload = dict(payload)
    payload["resolved"] = True
    payload["confirmed"] = confirmed
    pending.payload = payload
    await session.flush()
    return pending, confirmed


async def apply(session: AsyncSession, outcome: tuple[EventLog, bool]) -> None:
    """Применить подтверждённый/отклонённый трансфер и объявить результат.

    Зовётся из обработчика сообщений после `consume_confirmation`. При «да»
    закрываем текущее назначение и создаём новое (`loser.assign_worm_to`), затем
    выдаём ачивку «Червь-господин» новому владельцу и объявляем в чат.
    """
    from app.db.models import User
    from app.services import loser
    from app.services.game import awards, journal

    pending, confirmed = outcome
    payload = pending.payload or {}
    if not confirmed:
        await journal.send_now(
            "🪱 Передача отменена — господин остаётся прежним.", feature="worm"
        )
        return
    target_id = payload.get("target_user_id")
    if target_id is None:
        return
    target_id = int(target_id)
    prev_name, row = await loser.assign_worm_to(session, target_id)
    if row is None:
        await journal.send_now(
            "🪱 Этот участник и так господин — передача не нужна.", feature="worm"
        )
        return
    # Э18: звание червя — та же ачивка «Червь-господин» и её юбилеи.
    await awards.worm_lord(session, target_id)
    await session.commit()
    new_user = await session.get(User, target_id)
    new_name = new_user.display_name if new_user else "новый владелец"
    text = (
        "🪱 <b>Передача власти</b>\n"
        f"{prev_name or 'Прежний господин'} слагает полномочия — новый "
        f"червь-господин: <b>{new_name}</b>. Слушаюсь, повелитель."
    )
    await journal.send_now(text, feature="worm")
    log.info("game.worm_transferred", new_worm=target_id)


# Единоразовое инфо-уведомление в общий чат — после деплоя фичи.
TRANSFER_NOTICE_TEXT = (
    "🪱 <b>Новая фишка: передача червя</b>\n\n"
    "Текущий червь-господин может передать бразды правления другому участнику "
    "прямо в чате: команда <code>/worm @кому</code> (или <code>/червь</code>).\n"
    "Бот попросит подтверждение — достаточно ответить <b>да</b> или <b>нет</b> "
    "реплаем на сообщение бота или обычным сообщением в течение 30 минут.\n"
    "На «да» бот сразу переоформит звание на нового владельца."
)
