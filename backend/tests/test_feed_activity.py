"""GHG11(8): участие в задании прямо из ленты.

Прод-наблюдение оператора: задание анонсируется в ленте, но по тапу по нему
нельзя поучаствовать — приходилось искать отдельный блок «Активности». Здесь
проверяем, что анонс открытого призыва приносит с собой интерфейс участия
(варианты/текст), а старый анонс с тем же текстом — нет.

БД-стенда нет: `_open_prompts` подменяем заглушкой, остальное — чистая логика.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.game import activity, feed, journal

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def _prompt(
    *,
    pid: int = 7,
    text: str = "🙊 Признайся в чём угодно одним сообщением",
    answers: list[dict] | None = None,
    created_at: datetime = NOW,
    winner_user_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=pid,
        code="confess",
        text=text,
        answers=answers
        if answers is not None
        else [{"matcher": r"^.{12,}$", "xp": 30, "label": None, "media": False}],
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
        winner_user_id=winner_user_id,
    )


def _event(text: str, at: datetime = NOW) -> dict:
    return feed._item(
        source="journal",
        row_id="journal:42",
        kind="event",
        at=at,
        text=text,
        user=None,
    )


def test_match_finds_fresh_announcement():
    prompt = _prompt()
    item = _event(prompt.text)
    assert feed.match_prompt_activity(item, [prompt]) is prompt


def test_match_ignores_old_announcement_of_same_text():
    """Тот же текст неделю назад (кулдаун) к новому промпту не привязываем."""
    prompt = _prompt(created_at=NOW)
    old = _event(prompt.text, at=NOW - timedelta(days=7))
    assert feed.match_prompt_activity(old, [prompt]) is None


def test_match_ignores_other_kinds_and_texts():
    prompt = _prompt()
    assert feed.match_prompt_activity(_event("другой текст"), [prompt]) is None
    achievement = feed._item(
        source="ach",
        row_id="ach:1",
        kind=feed.FEED_ACHIEVEMENT,
        at=NOW,
        text=prompt.text,
        user=None,
    )
    assert feed.match_prompt_activity(achievement, [prompt]) is None


def test_activity_detail_splits_options_and_text():
    prompt = _prompt(
        answers=[
            {"matcher": r"^да$", "xp": 10, "label": "да", "media": False},
            {"matcher": r"^.{12,}$", "xp": 0, "label": None, "media": False},
        ],
        winner_user_id=5,
    )
    detail = feed.activity_detail(prompt, user_id=5)
    assert detail["options"] == [{"label": "да", "xp": 10}]
    assert detail["needs_text"] is True
    assert detail["answered_by_me"] is True
    assert detail["expires_at"] == prompt.expires_at


@pytest.mark.asyncio
async def test_attach_details_adds_activity_to_event(monkeypatch):
    prompt = _prompt()

    async def fake_open(session, *, now):
        return [prompt]

    monkeypatch.setattr(feed, "_open_prompts", fake_open)

    items = [_event(prompt.text)]
    await feed._attach_details(None, items, user_id=1)
    assert items[0]["detail"]["activity"]["id"] == 7
    assert items[0]["detail"]["activity"]["needs_text"] is True


@pytest.mark.asyncio
async def test_attach_details_skips_when_no_open_prompt(monkeypatch):
    async def none_open(session, *, now):
        return []

    monkeypatch.setattr(feed, "_open_prompts", none_open)
    items = [_event("⚡️ что-то своё")]
    await feed._attach_details(None, items, user_id=1)
    assert items[0]["detail"] is None


def test_split_activity_options_rules():
    options, needs_text = activity.split_activity_options(
        [
            {"label": "да", "xp": 10},
            {"label": "нет", "xp": 50},
        ]
    )
    assert options == [("да", 10), ("нет", 50)]
    assert needs_text is False
    # Только медиа-ответ (мем) — всё равно даём ввод: ссылку можно прислать.
    options, needs_text = activity.split_activity_options(
        [{"matcher": r".*", "xp": 50, "label": None, "media": True}]
    )
    assert options == [] and needs_text is True
    # Пустой каталог ответов — тоже ввод.
    assert activity.split_activity_options([]) == ([], True)


def test_journal_kind_event_constant_matches():
    assert journal.KIND_EVENT == "event"
