"""GHG10 Э11: донат опыта имениннику.

Правила задания проверяются по одному — «сам себе», «только в день ДР», «раз в
году на получателя», «нечего дарить с нулём». Перевод проверяем на составе
вызовов: списание донору (отрицательная цена, `commit=False`) и начисление
имениннику должны уехать ОДНОЙ транзакцией, а ачивки — уже после неё.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.game import donations
from app.services.game.config import DONATION_AMOUNT

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class _FakeSession:
    def __init__(self, *, scalar: list | None = None) -> None:
        self._scalar = list(scalar or [])
        self.commits = 0
        self.rollbacks = 0

    async def scalar(self, *_a, **_k):
        return self._scalar.pop(0) if self._scalar else None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def env(monkeypatch):
    """Окружение «игра включена, ДР есть, переводы и ачивки записываются»."""
    state: dict = {"awards": [], "achievements": [], "xp": {1: 500, 2: 0}}

    async def _enabled(_session):
        return True

    async def _birthday(_session, _uid, _today):
        return True

    async def _get_xp(_session, user_id):
        return state["xp"].get(user_id, 0)

    async def _award(_session, user_id, event, **kw):
        state["awards"].append((user_id, event, kw))
        state["xp"][user_id] = state["xp"].get(user_id, 0) + (kw.get("points") or 0)

    async def _donation_sent(_session, donor_id, **kw):
        state["achievements"].append((donor_id, kw))

    monkeypatch.setattr(donations, "is_game_enabled", _enabled)
    monkeypatch.setattr(donations, "_birthday_today", _birthday)
    monkeypatch.setattr(donations.xp, "get_xp", _get_xp)
    monkeypatch.setattr(donations.xp, "award", _award)
    monkeypatch.setattr(donations.awards, "donation_sent", _donation_sent)
    return state


# --- чистые помощники --------------------------------------------------------

def test_marker_key_is_per_recipient_and_year():
    assert donations.marker_key(5, 2026) == "donation_sent:all:5:2026"
    assert donations.sent_prefix_for_year(2026).endswith("2026")


def test_teasing_message_mentions_name():
    text = donations.teasing_message("Митян", xp_now=0)
    assert "Митян" in text
    assert "0 XP" in text


def test_one_teasing_variant_names_the_amount():
    text = donations.teasing_message("Митян", xp_now=0, variant=2)
    assert str(DONATION_AMOUNT) in text


def test_teasing_variants_cycle():
    first = donations.teasing_message("X", xp_now=0, variant=0)
    second = donations.teasing_message("X", xp_now=0, variant=1)
    assert first != second


# --- отказы ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_game_disabled_blocks_donation(monkeypatch):
    async def _off(_session):
        return False

    monkeypatch.setattr(donations, "is_game_enabled", _off)
    res = await donations.donate(_FakeSession(), donor_id=1, recipient_id=2)
    assert res.code == "game_disabled"


@pytest.mark.asyncio
async def test_self_donation_is_refused(env):
    res = await donations.donate(_FakeSession(), donor_id=1, recipient_id=1)
    assert res.code == donations.SELF_DONATION
    assert env["awards"] == []


@pytest.mark.asyncio
async def test_only_on_the_actual_birthday(env, monkeypatch):
    async def _no(_session, _uid, _today):
        return False

    monkeypatch.setattr(donations, "_birthday_today", _no)
    res = await donations.donate(_FakeSession(), donor_id=1, recipient_id=2)
    assert res.code == donations.NOT_BIRTHDAY
    assert env["awards"] == []


@pytest.mark.asyncio
async def test_once_per_year_per_recipient(env):
    # scalar очереди: «маркер уже стоит» → 1.
    res = await donations.donate(_FakeSession(scalar=[1]), donor_id=1, recipient_id=2)
    assert res.code == donations.ALREADY_DONATED
    assert env["awards"] == []


@pytest.mark.asyncio
async def test_zero_balance_donor_is_refused(env):
    env["xp"][1] = 0
    res = await donations.donate(_FakeSession(scalar=[0]), donor_id=1, recipient_id=2)
    assert res.code == donations.NOT_ENOUGH_XP
    assert res.donor_xp == 0
    assert env["awards"] == []


# --- успешный перевод --------------------------------------------------------

@pytest.mark.asyncio
async def test_transfer_moves_exactly_the_donation(env):
    # scalar: маркер (0), «скольким подарил» (1), «живых участников» (6).
    session = _FakeSession(scalar=[0, 1, 6])
    res = await donations.donate(session, donor_id=1, recipient_id=2, at=NOW)

    assert res.ok and res.code == donations.OK
    donor, recipient = res.donor_xp, res.recipient_xp
    assert donor == 500 - DONATION_AMOUNT
    assert recipient == DONATION_AMOUNT
    # Общий счёт опыта в системе не растёт: списали столько же, сколько дали.
    assert donor + recipient == 500

    (donor_call, recipient_call) = env["awards"]
    assert donor_call[0] == 1 and donor_call[2]["points"] == -DONATION_AMOUNT
    # Первый award только flush'ит — коммит делает второй (одна транзакция).
    assert donor_call[2]["commit"] is False
    assert recipient_call[0] == 2 and recipient_call[2]["points"] == DONATION_AMOUNT


@pytest.mark.asyncio
async def test_achievements_come_after_the_transfer(env):
    session = _FakeSession(scalar=[0, 3, 6])
    res = await donations.donate(session, donor_id=1, recipient_id=2, at=NOW)
    assert res.recipients_this_year == 3
    assert res.live_participants == 6
    donor_id, kwargs = env["achievements"][0]
    assert donor_id == 1
    assert kwargs == {"recipients_this_year": 3, "live_participants": 6}


@pytest.mark.asyncio
async def test_lost_race_is_not_a_500(env, monkeypatch):
    """Гонка двух донатов: проигравший (IntegrityError) получает отказ, не падение.

    Сценарий с двойным тапом в мини-аппе: оба запроса прошли проверки, но
    уникальный индекс `xp_grants` пропустил только один маркер. Второй должен
    откатиться ЦЕЛИКОМ (одна транзакция на перевод) и ответить как на повтор.
    """
    from sqlalchemy.exc import IntegrityError

    async def _explode(*_a, **_k):
        raise IntegrityError("stmt", {}, Exception("uq"))

    monkeypatch.setattr(donations.xp, "award", _explode)
    session = _FakeSession(scalar=[0, 500, 6])
    res = await donations.donate(session, donor_id=1, recipient_id=2, at=NOW)
    assert res.code == donations.ALREADY_DONATED
    assert res.ok is False
    assert session.rollbacks == 1
    # Ачивки после проигранной гонки не начисляются (перевода не было).
    assert env["achievements"] == []


@pytest.mark.asyncio
async def test_marker_discriminator_is_recipient_and_year(env):
    session = _FakeSession(scalar=[0, 1, 6])
    await donations.donate(session, donor_id=1, recipient_id=2, at=NOW)
    donor_call = env["awards"][0]
    assert donor_call[2]["discriminator"] == f"2:{NOW.year}"
