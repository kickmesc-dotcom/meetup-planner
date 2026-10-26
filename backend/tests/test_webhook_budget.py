"""Вебхук обязан отвечать Telegram, пока Telegram ещё ждёт.

Почему это отдельный тест. Владелец написал, что `/changelog` отвечает через
час или шесть. Причина оказалась не в команде, а в вебхуке: он ждал обработчик
целиком, выходил за 60-секундное окно Telegram, и Telegram повторял апдейт
позже — вторым (или единственным) ответом. Здесь проверяются три обещания:

1. медленный обработчик НЕ держит ответ дольше бюджета;
2. работа при этом не теряется — задача докручивается в фоне;
3. повторная доставка того же `update_id` не обрабатывается дважды.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402

from app.bot import webhook as webhook_module  # noqa: E402
from app.db.org_models import current_org_id  # noqa: E402

ORG_ID = 4


class _FakeRequest:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


class _FakeUpdate:
    @staticmethod
    def model_validate(payload):  # noqa: ANN001, ANN205
        return SimpleNamespace(update_id=payload["update_id"])


class _FakeDispatcher:
    """Обработчик с настраиваемой длительностью."""

    def __init__(self, *, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls: list[int] = []
        self.orgs: list[object] = []
        self.finished = 0

    async def feed_update(self, bot, update) -> None:  # noqa: ANN001
        self.calls.append(update.update_id)
        self.orgs.append(current_org_id.get())
        if self.delay:
            await asyncio.sleep(self.delay)
        self.finished += 1


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    webhook_module.reset_seen_updates()

    async def _org(session, secret):  # noqa: ANN001, ANN202
        return ORG_ID

    monkeypatch.setattr(webhook_module, "resolve_org", _org)
    monkeypatch.setattr(webhook_module, "Update", _FakeUpdate)
    monkeypatch.setattr(webhook_module, "bot_for_org", lambda org_id: f"bot-{org_id}")
    yield
    webhook_module.reset_seen_updates()


def _install(
    monkeypatch,
    dispatcher: _FakeDispatcher,
    *,
    budget: float | None = None,
) -> None:
    """Подменить диспетчер и — когда нужен — бюджет ответа.

    Бюджет подменяем функцией, а не env: env проходит через защитный зажим (не
    меньше трёх секунд), и тест на «медленный апдейт» иначе занимал бы ровно эти
    три секунды. Сам зажим проверяется отдельно.
    """
    monkeypatch.setattr(webhook_module, "get_dispatcher", lambda: dispatcher)
    if budget is not None:
        monkeypatch.setattr(
            webhook_module, "response_budget_seconds", lambda: budget
        )


async def test_slow_handler_does_not_hold_the_webhook(monkeypatch) -> None:
    """Обработчик, который длится дольше бюджета, не держит ответ."""
    dispatcher = _FakeDispatcher(delay=0.6)
    _install(monkeypatch, dispatcher, budget=0.2)

    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await webhook_module.tg_webhook(_FakeRequest({"update_id": 11}), None, "s")
    elapsed = loop.time() - started

    assert result == {"ok": True}
    # Ответ ушёл сразу после бюджета, а не через 0.6 секунды работы обработчика.
    assert elapsed < 0.4, f"вебхук держал ответ {elapsed:.2f} с"
    # Работа не потеряна: задача осталась жить и докрутится сама.
    assert dispatcher.finished == 0
    assert await webhook_module.wait_pending_tasks(timeout=3.0) == 0
    assert dispatcher.calls == [11]
    assert dispatcher.finished == 1


async def test_slow_update_keeps_the_org_context(monkeypatch) -> None:
    """Фоновая задача наследует организацию апдейта, а не берёт чужую."""
    dispatcher = _FakeDispatcher(delay=0.3)
    _install(monkeypatch, dispatcher, budget=0.1)

    await webhook_module.tg_webhook(_FakeRequest({"update_id": 12}), None, "s")
    assert dispatcher.orgs == [ORG_ID]

    await webhook_module.wait_pending_tasks(timeout=3.0)
    assert dispatcher.orgs == [ORG_ID]


async def test_fast_update_is_processed_before_the_answer(monkeypatch) -> None:
    """Обычный апдейт отрабатывается целиком: ждать бюджет незачем."""
    dispatcher = _FakeDispatcher()
    _install(monkeypatch, dispatcher)

    result = await webhook_module.tg_webhook(_FakeRequest({"update_id": 13}), None, "s")

    assert result == {"ok": True}
    assert dispatcher.finished == 1


async def test_repeated_delivery_is_not_processed_twice(monkeypatch) -> None:
    """Повтор апдейта Telegram не печатает вторую копию ответа."""
    dispatcher = _FakeDispatcher()
    _install(monkeypatch, dispatcher)
    request = _FakeRequest({"update_id": 14})

    assert await webhook_module.tg_webhook(request, None, "s") == {"ok": True}
    assert await webhook_module.tg_webhook(request, None, "s") == {"ok": True}

    assert dispatcher.calls == [14], "повтор доставки обработан заново"


def test_seen_updates_are_bounded_and_expire() -> None:
    """Память дедупликации не растёт без предела и забывает старое."""
    webhook_module.reset_seen_updates()

    assert webhook_module.remember_update(1, now=1000.0) is False
    assert webhook_module.remember_update(1, now=1001.0) is True
    # Через TTL от последнего касания тот же id больше не считается повтором:
    # держать историю вечно нечем, да и незачем.
    late = 1001.0 + webhook_module.SEEN_UPDATE_TTL_SECONDS + 1
    assert webhook_module.remember_update(1, now=late) is False

    for update_id in range(10_000, 10_000 + webhook_module.SEEN_UPDATE_MAX + 100):
        webhook_module.remember_update(update_id, now=late)
    assert len(webhook_module._seen_updates) <= webhook_module.SEEN_UPDATE_MAX + 1


def test_unknown_update_id_is_not_deduplicated() -> None:
    """Апдейт без id лучше обработать дважды, чем выбросить."""
    webhook_module.reset_seen_updates()
    assert webhook_module.remember_update(None) is False
    assert webhook_module.remember_update(None) is False


def test_changelog_budget_fits_the_webhook_window(monkeypatch) -> None:
    """Бюджет команды обязан быть меньше бюджета ответа — иначе снова «через 6 часов».

    Это тот самый инвариант, из-за которого владелец жаловался: раньше одна
    команда могла занять 154 с при окне Telegram в 60 с. Тест держит связь
    двух чисел: если кто-то добавит «ещё одну попытку», он сломает этот тест, а
    не поведение в продакшене.
    """
    monkeypatch.delenv("WEBHOOK_RESPONSE_BUDGET_SECONDS", raising=False)

    from app.bot.handlers import changelog as changelog_handler

    budget = webhook_module.response_budget_seconds()
    assert changelog_handler.TOTAL_BUDGET_SECONDS < budget
    assert budget < 60.0, "Telegram ждёт ответ на вебхук 60 секунд"


def test_budget_is_clamped_to_sane_range(monkeypatch) -> None:
    """Бюджет нельзя выкрутить в абсурд: Telegram ждёт 60 секунд."""
    monkeypatch.setenv("WEBHOOK_RESPONSE_BUDGET_SECONDS", "600")
    assert webhook_module.response_budget_seconds() == 55.0
    monkeypatch.setenv("WEBHOOK_RESPONSE_BUDGET_SECONDS", "0.01")
    assert webhook_module.response_budget_seconds() == 3.0
    monkeypatch.setenv("WEBHOOK_RESPONSE_BUDGET_SECONDS", "не число")
    assert webhook_module.response_budget_seconds() == (
        webhook_module.DEFAULT_RESPONSE_BUDGET_SECONDS
    )
