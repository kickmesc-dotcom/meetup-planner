"""GHG11(17/18): окно приёма ответов — общее правило для всех механик.

Проверяем три вещи:

* чистое правило `accept.window_minutes_for` (0 = «как сейчас», положительное —
  переопределение, мусор — не роняем);
* настройку по режимам доставки и её границы (0…1440) плюс контракт ручки
  `/admin/game/social`;
* что к окну РЕАЛЬНО подключены обе механики: голосовые задания
  (`voice.task_window_minutes`) и случайные события-призывы
  (`events.build_prompt_posts(window_minutes=...)`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app._legacy.services.game import accept, events, voice
from app._legacy.services.game.config import ACCEPT_WINDOW_MAX_MINUTES
from app._legacy.services.game.events_catalog import PROMPTS
from app._legacy.services.game.voice_catalog import TASKS

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

# Призыв, у которого есть поясняющий пост с правилами: именно там и живёт
# обещание срока («Ответы принимаются …»), поэтому окно проверяем по нему.
RULES_PROMPT = next(p for p in PROMPTS if p.needs_rules)


# --------------------------------------------------------------------------
# Чистое правило
# --------------------------------------------------------------------------


def test_window_minutes_for_zero_means_catalog_default():
    assert accept.window_minutes_for(override_minutes=0, default_minutes=120) == 120
    # Мусор и отрицательное из конфига — тоже каталог, а не «окно ноль секунд».
    assert accept.window_minutes_for(override_minutes=-5, default_minutes=30) == 30
    assert accept.window_minutes_for(override_minutes=None, default_minutes=60) == 60


def test_window_minutes_for_override_wins():
    assert accept.window_minutes_for(override_minutes=480, default_minutes=30) == 480
    assert accept.window_minutes_for(override_minutes=90, default_minutes=120) == 90


def test_default_window_for_mode_is_safe():
    """Чат и «чат + апп» — как были, мини-апп — восемь часов, прочее — «как сейчас»."""
    assert accept.default_window_for_mode("chat") == 0
    assert accept.default_window_for_mode("both") == 0
    assert accept.default_window_for_mode("app") == 480
    assert accept.default_window_for_mode("off") == 0
    assert accept.default_window_for_mode("что-то новое") == 0


# --------------------------------------------------------------------------
# Настройка по режимам (фейк-сессия под `_get_value`)
# --------------------------------------------------------------------------


class _CfgRow:
    def __init__(self, value: str) -> None:
        self.value = value


class _CfgSession:
    """Фейк-сессия под `_get_value`: `session.get(AdminConfig, key)`."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    async def get(self, _model, key: str):
        value = self.values.get(key)
        return _CfgRow(value) if value is not None else None


@pytest.mark.asyncio
async def test_accept_window_defaults_by_delivery_mode():
    from app.services.admin_config import get_accept_window_minutes

    session = _CfgSession()
    assert await get_accept_window_minutes(session, "chat") == 0
    assert await get_accept_window_minutes(session, "both") == 0
    assert await get_accept_window_minutes(session, "app") == 480

    # Значение из конфига перебивает дефолт (все три режима настраиваются).
    override = _CfgSession(
        {
            "game.accept.window.chat_minutes": "90",
            "game.accept.window.both_minutes": "120",
            "game.accept.window.app_minutes": "60",
        }
    )
    assert await get_accept_window_minutes(override, "chat") == 90
    assert await get_accept_window_minutes(override, "both") == 120
    assert await get_accept_window_minutes(override, "app") == 60

    # Незнакомый режим (в т.ч. `off`) — «как сейчас», а не чужое окно.
    assert await get_accept_window_minutes(session, "off") == 0
    # Мусор в конфиге — дефолт режима, не падение.
    junk = _CfgSession({"game.accept.window.chat_minutes": "абв"})
    assert await get_accept_window_minutes(junk, "chat") == 0


@pytest.mark.asyncio
async def test_set_accept_window_clamps_and_rejects_unknown_mode(monkeypatch):
    from app.services import admin_config

    written: dict[str, str] = {}
    keys = {
        "chat": admin_config.GAME_ACCEPT_WINDOW_CHAT_KEY,
        "both": admin_config.GAME_ACCEPT_WINDOW_BOTH_KEY,
        "app": admin_config.GAME_ACCEPT_WINDOW_APP_KEY,
    }

    async def fake_set(_session, key: str, value: str) -> None:
        written[key] = value

    monkeypatch.setattr(admin_config, "_set_value", fake_set)
    await admin_config.set_accept_window_minutes(None, "app", 99999)
    assert written[keys["app"]] == str(ACCEPT_WINDOW_MAX_MINUTES)
    await admin_config.set_accept_window_minutes(None, "chat", -10)
    assert written[keys["chat"]] == "0"
    # 0 — это «как сейчас», его надо уметь вернуть обратно.
    await admin_config.set_accept_window_minutes(None, "both", 0)
    assert written[keys["both"]] == "0"
    with pytest.raises(ValueError):
        await admin_config.set_accept_window_minutes(None, "off", 60)


def test_social_payload_carries_and_bounds_accept_windows():
    """Контракт ручки /admin/game/social: дефолты и границы окна приёма."""
    from pydantic import ValidationError

    from app.schemas.game import GameSocialIn, GameSocialOut

    out = GameSocialOut()
    assert (
        out.accept_window_chat_minutes,
        out.accept_window_both_minutes,
        out.accept_window_app_minutes,
    ) == (0, 0, 480)

    body = GameSocialIn(accept_window_app_minutes=1440)
    assert body.accept_window_app_minutes == 1440
    with pytest.raises(ValidationError):
        GameSocialIn(accept_window_app_minutes=1441)
    with pytest.raises(ValidationError):
        GameSocialIn(accept_window_chat_minutes=-1)


# --------------------------------------------------------------------------
# Обе механики реально подключены к окну
# --------------------------------------------------------------------------


def test_events_followup_uses_the_actual_window():
    """Правила призыва обещают ФАКТИЧЕСКОЕ окно, а не каталог (GHG11(18))."""
    prompt = RULES_PROMPT
    minutes = 480
    posts = events.build_prompt_posts(prompt, window_minutes=minutes)
    assert posts[0] == prompt.text
    assert "8 ч" in posts[1]
    # Без переопределения — окно из каталога (прежнее поведение не поехало),
    # причём в человеческом виде: «2 ч» вместо «120 мин».
    default_posts = events.build_prompt_posts(prompt)
    expected = (
        f"{prompt.ttl_minutes // 60} ч"
        if prompt.ttl_minutes % 60 == 0
        else f"{prompt.ttl_minutes} мин"
    )
    assert expected in default_posts[1]
    assert events.build_followup_text(ttl_minutes=minutes) == posts[1]


def test_events_window_applies_only_to_windowed_prompts():
    """У очевидных призывов фоллоу-поста нет — окно их не касается."""
    obvious = [p for p in PROMPTS if not p.needs_rules]
    assert obvious, "в каталоге должен быть хотя бы один призыв без правил"
    for prompt in obvious:
        assert events.build_prompt_posts(prompt, window_minutes=480) == [prompt.text]


def test_voice_and_events_share_one_window_rule():
    """Одно и то же переопределение двигает обе механики."""
    task = TASKS[0]
    prompt = RULES_PROMPT
    assert voice.task_window_minutes(task, override_minutes=240) == 240
    assert events.build_prompt_posts(prompt, window_minutes=240)[1].count("4 ч") == 1
    # А «0 = как сейчас» возвращает каждую механику к её собственному каталогу —
    # у задания и у призыва сроки разные, и это ожидаемо.
    assert voice.task_window_minutes(task, override_minutes=0) == task.window_minutes
    assert prompt.ttl_minutes != task.window_minutes


def test_prompt_expiry_matches_window():
    """Тот же счёт, что в `run_events_job`: expires_at = момент + окно."""
    prompt = RULES_PROMPT
    window = accept.window_minutes_for(override_minutes=480, default_minutes=prompt.ttl_minutes)
    assert NOW + timedelta(minutes=window) == NOW + timedelta(minutes=480)
