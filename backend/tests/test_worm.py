"""GHG6 E8 — «Червь-пидор»: чистая логика broska/композиции сообщения.

Интеграция с БД (создание `WormAssignment`, закрытие предыдущего, partial
unique index) проверяется руками при первом ролле — отдельный sqlite-стенд
в проект не тащим (его нет для других сервисов). Здесь — только декомпозируемая
часть: `decide_worm` и `compose_loser_message`.
"""
from __future__ import annotations

from typing import Any

from app.services.loser import (
    MasterSycophancy,
    RollExtras,
    WormEvent,
    WORM_REASON_TEXT,
    compose_loser_message,
    decide_worm,
    resolve_master_sycophancy,
)


# ----- decide_worm -----

def test_decide_worm_disabled_never_triggers():
    assert decide_worm(enabled=False, chance=1.0, rng_value=0.0) is False
    assert decide_worm(enabled=False, chance=0.5, rng_value=0.4) is False


def test_decide_worm_zero_chance_never_triggers():
    assert decide_worm(enabled=True, chance=0.0, rng_value=0.0) is False


def test_decide_worm_boundary_rng_below_chance_triggers():
    # rng_value < chance → True
    assert decide_worm(enabled=True, chance=0.01, rng_value=0.009) is True


def test_decide_worm_boundary_rng_equal_chance_does_not_trigger():
    # rng_value == chance → False (строгое <)
    assert decide_worm(enabled=True, chance=0.01, rng_value=0.01) is False


def test_decide_worm_full_chance_always_triggers():
    # При chance=1.0 любое rng_value < 1.0 → True
    assert decide_worm(enabled=True, chance=1.0, rng_value=0.99) is True


# ----- compose_loser_message -----

def test_compose_regular_loser_no_extras():
    out = compose_loser_message(
        loser_name="Серёжа Neo",
        reason_text="воюет не в ту сторону",
        roller_name="Никита",
        loser_count=3,
    )
    assert "Серёжа Neo" in out
    assert "воюет не в ту сторону" in out
    assert "3-й раз" in out
    assert "Никита" in out
    assert "🪱" not in out
    assert "ЧЕРВЬ" not in out


def test_compose_worm_message_replaces_layout():
    out = compose_loser_message(
        loser_name="Дмитрий-JDM",
        reason_text=WORM_REASON_TEXT,
        roller_name="Никита",
        loser_count=5,
        extras=RollExtras(worm=WormEvent(triggered=True)),
    )
    assert "ОСОБАЯ НОМИНАЦИЯ" in out
    assert "🪱" in out
    assert "Дмитрий-JDM" in out
    # Обычные слова шаблона лоха («Причина:») не должны попадать в worm-сообщение
    assert "Причина:" not in out


def test_compose_worm_with_previous_holder_mentions_transfer():
    out = compose_loser_message(
        loser_name="Никита",
        reason_text=WORM_REASON_TEXT,
        extras=RollExtras(worm=WormEvent(triggered=True, prev_worm_name="Русланище")),
    )
    assert "Русланище" in out
    assert "слагает полномочия" in out


def test_compose_worm_without_previous_holder_no_transfer_line():
    out = compose_loser_message(
        loser_name="Никита",
        reason_text=WORM_REASON_TEXT,
        extras=RollExtras(worm=WormEvent(triggered=True, prev_worm_name=None)),
    )
    assert "слагает полномочия" not in out


def test_compose_worm_same_user_repeat_no_self_transfer_line():
    # Если предыдущий червь — тот же юзер (повторное выпадение), линии
    # «слагает полномочия» быть не должно.
    out = compose_loser_message(
        loser_name="Никита",
        reason_text=WORM_REASON_TEXT,
        extras=RollExtras(worm=WormEvent(triggered=True, prev_worm_name="Никита")),
    )
    assert "слагает полномочия" not in out


# ----- T3.6 (г): расширенный анонс «что даёт звание господина» -----

def test_compose_worm_includes_announce_extra_when_present():
    extra = "С данной минуты Никита — мой великий господин.\nШанс был 1%."
    out = compose_loser_message(
        loser_name="Никита",
        reason_text=WORM_REASON_TEXT,
        extras=RollExtras(worm=WormEvent(triggered=True, announce_extra=extra)),
    )
    assert "мой великий господин" in out
    assert "Шанс был 1%" in out
    # блок идёт ВНУТРИ worm-анонса
    assert "ЧЕРВЬ-ПИДОР" in out


def test_compose_worm_without_announce_extra_unchanged():
    # announce_extra=None (режим выключен) → анонс как раньше, без лишних строк.
    out = compose_loser_message(
        loser_name="Никита",
        reason_text=WORM_REASON_TEXT,
        extras=RollExtras(worm=WormEvent(triggered=True, announce_extra=None)),
    )
    assert "господин" not in out.lower()


# ----- T3.6 (а): подхалимский префикс/суффикс при лохе-господине -----

def test_compose_regular_loser_with_sycophancy_prefix_and_suffix():
    out = compose_loser_message(
        loser_name="Серж",
        reason_text="слился со встречи",
        extras=RollExtras(
            worm_master=MasterSycophancy(
                prefix="С прискорбием сообщаю", suffix="Вопиющая несправедливость."
            )
        ),
    )
    lines = out.split("\n")
    # префикс — ПЕРВОЙ строкой, суффикс — ПОСЛЕДНЕЙ
    assert "С прискорбием сообщаю" in lines[0]
    assert "Вопиющая несправедливость." in lines[-1]
    # обычный лох-шаблон сохранён
    assert "Лох дня" in out
    assert "Причина: слился со встречи" in out


def test_compose_regular_loser_prefix_only():
    out = compose_loser_message(
        loser_name="Серж",
        reason_text="x",
        extras=RollExtras(worm_master=MasterSycophancy(prefix="Увы", suffix=None)),
    )
    assert out.split("\n")[0] == "<i>Увы</i>"


def test_compose_regular_loser_no_sycophancy_unchanged():
    # worm_master=None (обычный лох, не господин) → шаблон как раньше.
    out = compose_loser_message(loser_name="Серж", reason_text="x")
    assert out.startswith("🎲 <b>Лох дня</b> — Серж!")


class _FakeWormSession:
    """Минимальный stub под resolve_master_sycophancy — покрывает ТОЛЬКО
    короткозамкнутые ветки (режим выключен / юзер не червь), которые
    возвращаются до запросов к пулам. Реальный путь с выбором фразы
    проверяется руками при первом ролле (паттерн test_worm/test_loser_*)."""

    def __init__(self, *, master_enabled: bool, current_worm_uid: int | None) -> None:
        self._master_enabled = master_enabled
        self._worm_uid = current_worm_uid

    async def get(self, *_a: Any, **_kw: Any) -> Any:  # admin_config._get_value path
        return None

    async def scalar(self, stmt: Any) -> Any:
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        # is_worm_master_enabled читает worm_master.enabled через _get_value→session.get,
        # сюда попадает запрос get_current_worm (WormAssignment WHERE ended_at IS NULL).
        if "worm_assignments" in compiled.lower():
            if self._worm_uid is None:
                return None
            from app.db.models import WormAssignment

            return WormAssignment(user_id=self._worm_uid)
        return None


class _FakeUser:
    def __init__(self, uid: int, name: str = "Господин") -> None:
        self.id = uid
        self.display_name = name


async def test_resolve_sycophancy_returns_none_when_mode_disabled(monkeypatch: Any) -> None:
    import app.services.admin_config as ac

    async def _disabled(_session: Any) -> bool:
        return False

    monkeypatch.setattr(ac, "is_worm_master_enabled", _disabled)
    out = await resolve_master_sycophancy(
        _FakeWormSession(master_enabled=False, current_worm_uid=1), _FakeUser(1)
    )
    assert out is None


async def test_resolve_sycophancy_returns_none_when_user_not_worm(monkeypatch: Any) -> None:
    import app.services.admin_config as ac

    async def _enabled(_session: Any) -> bool:
        return True

    monkeypatch.setattr(ac, "is_worm_master_enabled", _enabled)
    # текущий червь — uid=2, а лох — uid=1 → подхалимажа нет
    out = await resolve_master_sycophancy(
        _FakeWormSession(master_enabled=True, current_worm_uid=2), _FakeUser(1)
    )
    assert out is None
