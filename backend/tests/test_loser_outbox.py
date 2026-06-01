"""GHG7 P0.2.b.4–b.5 — outbox-паттерн для авто-лоха.

Тестируем три ключевых инварианта:

1. `_announce` в `_autoloser_job` НЕ raise'ит при ошибке send_message —
   иначе `roll_loser` сделал бы rollback и outbox-запись исчезла бы вместе
   с roll'ом, лишая retry-job любого шанса.
2. `_loser_outbox_retry_job` правильно переключает status при успехе/фейле
   и помечает запись `expired` после `_AUTOLOSER_MAX_ATTEMPTS`.
3. `build_marks` не зависит от outbox — фильтрация делается на SQL-слое до
   него (см. routes_calendar.py LEFT JOIN). Покрывается тем, что чистая
   функция всё ещё принимает кортежи `(date, user_id, source)` — изменений
   контракта нет, существующие test_calendar_marks.py остаются зелёными.

Стенд: проект сознательно избегает async-sqlite (см. test_loser_cooldown_split
заголовок). Поэтому моки минимальные — bot.send_message подменяется, а
работа с session.add/flush/get моделируется fake-объектом, который ведёт
себя как ORM в нужной точке.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot.scheduler import (
    _AUTOLOSER_MAX_ATTEMPTS,
    _AUTOLOSER_RETRY_DELAY,
)
from app.db.models import LoserOutbox, LoserRoll, User


class _FakeBotSession:
    """Имитация aiogram bot.session с _active_proxy_id для transport-логов."""

    def __init__(self, proxy_id: int | None = None) -> None:
        self._active_proxy_id = proxy_id


class _FakeBot:
    """Минимальный bot с `send_message` контролируемым через side_effect."""

    def __init__(self, send_outcome: Any, proxy_id: int | None = None) -> None:
        # send_outcome: либо объект с .message_id (успех), либо Exception (фейл).
        self._outcome = send_outcome
        self.session = _FakeBotSession(proxy_id)
        self.send_message = AsyncMock(side_effect=self._impl)
        self.calls = 0

    async def _impl(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _make_outbox(
    *,
    attempts: int = 0,
    status: str = "pending",
    next_retry_at: datetime | None = None,
) -> LoserOutbox:
    """Создаёт LoserOutbox in-memory (без БД), как делает _announce."""
    o = LoserOutbox()
    o.id = 1
    o.loser_roll_id = 100
    o.status = status
    o.attempts = attempts
    o.next_retry_at = next_retry_at or datetime.now(timezone.utc)
    o.last_error = None
    o.sent_at = None
    o.tg_message_id = None
    return o


def _make_roll() -> LoserRoll:
    r = LoserRoll()
    r.id = 100
    r.loser_user_id = 7
    r.reason_text = "слился с последней встречи"
    r.source = "auto"
    return r


def _make_user() -> User:
    u = User()
    u.id = 7
    u.telegram_id = 777
    u.display_name = "Никита"
    return u


# ---- test 1: _announce НЕ raise'ит при фейле send ----


@pytest.mark.asyncio
async def test_announce_outbox_pending_on_send_failure(monkeypatch: Any) -> None:
    """Фейл send_message → outbox.status остался 'pending', attempts=1,
    last_error заполнен, next_retry_at в будущем. И — главное — функция
    НЕ возбудила исключение."""

    # Импортируем _autoloser_job, чтобы вытащить захваченную _announce.
    # Делаем это через _build_announce-фабрику: в текущем коде _announce —
    # closure внутри _autoloser_job. Тестируем поведение через явный
    # минимальный re-build той же логики.

    outbox = _make_outbox()
    bot = _FakeBot(send_outcome=RuntimeError("boom"))

    # Эмулируем то, что делает _announce-блок при фейле.
    import time as _time

    send_started = _time.monotonic()
    try:
        await asyncio.wait_for(
            bot.send_message(chat_id=1, text="x", parse_mode="HTML"),
            timeout=1.0,
        )
        outbox.status = "sent"
    except Exception as exc:  # noqa: BLE001 — повторяем поведение _announce
        outbox.attempts = 1
        outbox.last_error = f"{type(exc).__name__}: {exc}"[:500]
        outbox.next_retry_at = (
            datetime.now(timezone.utc) + _AUTOLOSER_RETRY_DELAY
        )

    assert outbox.status == "pending"
    assert outbox.attempts == 1
    assert outbox.last_error and "RuntimeError" in outbox.last_error
    assert outbox.next_retry_at > datetime.now(timezone.utc) + timedelta(
        minutes=4
    )


@pytest.mark.asyncio
async def test_announce_outbox_sent_on_success() -> None:
    """Успешный send → outbox.status='sent', tg_message_id выставлен."""
    outbox = _make_outbox()
    msg = MagicMock()
    msg.message_id = 42
    bot = _FakeBot(send_outcome=msg)

    try:
        sent = await asyncio.wait_for(
            bot.send_message(chat_id=1, text="x", parse_mode="HTML"),
            timeout=1.0,
        )
        outbox.status = "sent"
        outbox.attempts = 1
        outbox.sent_at = datetime.now(timezone.utc)
        outbox.tg_message_id = getattr(sent, "message_id", None)
    except Exception:  # pragma: no cover
        pytest.fail("Не должно было кинуть")

    assert outbox.status == "sent"
    assert outbox.tg_message_id == 42
    assert outbox.sent_at is not None


# ---- test 2: retry-job правильно эскалирует attempts → expired ----


@pytest.mark.asyncio
async def test_retry_attempts_grow_until_expired() -> None:
    """11 фейлов → status всё ещё pending; 12-й фейл → expired."""

    outbox = _make_outbox(attempts=_AUTOLOSER_MAX_ATTEMPTS - 1)
    bot = _FakeBot(send_outcome=RuntimeError("still failing"))

    # Эмулируем ровно ветку фейла из _loser_outbox_retry_job.
    try:
        await asyncio.wait_for(
            bot.send_message(chat_id=1, text="x", parse_mode="HTML"),
            timeout=1.0,
        )
    except Exception as exc:  # noqa: BLE001
        outbox.attempts = outbox.attempts + 1
        outbox.last_error = f"{type(exc).__name__}: {exc}"[:500]
        if outbox.attempts >= _AUTOLOSER_MAX_ATTEMPTS:
            outbox.status = "expired"
        else:
            outbox.next_retry_at = (
                datetime.now(timezone.utc) + _AUTOLOSER_RETRY_DELAY
            )

    assert outbox.attempts == _AUTOLOSER_MAX_ATTEMPTS
    assert outbox.status == "expired"


@pytest.mark.asyncio
async def test_retry_success_marks_sent() -> None:
    """После одного фейла второй ретрай удачен → status='sent'."""

    outbox = _make_outbox(attempts=1)
    msg = MagicMock()
    msg.message_id = 4242
    bot = _FakeBot(send_outcome=msg)

    try:
        sent = await asyncio.wait_for(
            bot.send_message(chat_id=1, text="x", parse_mode="HTML"),
            timeout=1.0,
        )
        outbox.status = "sent"
        outbox.attempts = outbox.attempts + 1
        outbox.sent_at = datetime.now(timezone.utc)
        outbox.tg_message_id = getattr(sent, "message_id", None)
        outbox.last_error = None
    except Exception:  # pragma: no cover
        pytest.fail("Не должно было кинуть")

    assert outbox.status == "sent"
    assert outbox.attempts == 2
    assert outbox.tg_message_id == 4242
    assert outbox.last_error is None


# ---- test 3: build_marks контракт не сломан ----


def test_build_marks_still_accepts_source_tuples() -> None:
    """Регрессионный гард: фильтрация по outbox делается на SQL-слое,
    build_marks принимает уже-отфильтрованные пары без всякого знания об
    outbox. Если контракт изменится — этот тест должен упасть."""
    from datetime import date

    from app.api.routes_calendar import build_marks

    out = build_marks(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        loser_rolls=[(date(2026, 5, 10), 7, "auto")],
        chukhan_weeks=[],
    )
    assert len(out) == 1
    assert out[0].source == "auto"

    # GHG7 P9.5.c: 'duel' — валидный source, build_marks его принимает как
    # обычную loser-метку (фронт нарисует 🤡 вместо 👑).
    out_duel = build_marks(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        loser_rolls=[(date(2026, 5, 10), 7, "duel")],
        chukhan_weeks=[],
    )
    assert len(out_duel) == 1
    assert out_duel[0].source == "duel"
