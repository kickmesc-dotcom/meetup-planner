"""GHG11(10): осмысленные реакции на медиа, источник ленты «media» и превью
последней активности в профиле.

Async-БД-стенда нет (как и в остальных игровых тестах): работаем фейковыми
сессиями из очередей и подменёнными сервисами. Проверяем решения, а не SQL:
* какой ТЕКСТ получает запись ленты («на фото — 🔥», «на подборку (5 файлов)»);
* что пост реально хранит тип медиа и саму реакцию;
* что автору реакции начисляется опыт с дискриминатором-сообщением;
* что `feed._media_items` собирает запись из поста;
* что `ui.show_last_seen` по умолчанию включён и выключается.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import admin_config as ac
from app.services.game import awards, config as game_config, feed, memes, presence
from app.services.media_reactions import describe_media, reaction_announcement

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


# --- чистое ядро текста анонса ----------------------------------------------

def test_describe_media_single_words():
    assert describe_media("single", "photo", 1) == "фото"
    assert describe_media("single", "video", 1) == "видео"
    assert describe_media("single", "animation", 1) == "гифку"
    assert describe_media("single", "sticker", 1) == "стикер"
    # Неизвестный/пустой тип — не падаем и не показываем пустоту.
    assert describe_media("single", None, None) == "фото"
    assert describe_media("single", "weird", 1) == "медиа"


def test_describe_media_collection_counts_files():
    assert describe_media("collection", "photo", 5) == "подборку (5 файлов)"
    # Счётчик подстрахован: подборка — это всегда ≥2 файлов.
    assert describe_media("collection", None, 0) == "подборку (2 файлов)"


def test_reaction_announcement_with_emoji():
    assert (
        reaction_announcement(
            kind="single", media_type="photo", count=1, emoji="🔥", phrase=None
        )
        == "Бот отреагировал на фото — 🔥"
    )


def test_reaction_announcement_with_phrase_quoted():
    assert (
        reaction_announcement(
            kind="collection",
            media_type="photo",
            count=5,
            emoji=None,
            phrase="Сегодня лучше",
        )
        == "Бот отреагировал на подборку (5 файлов) — «Сегодня лучше»"
    )


def test_reaction_announcement_both_and_none():
    both = reaction_announcement(
        kind="single", media_type="video", count=1, emoji="🔥", phrase="жиза"
    )
    assert both == "Бот отреагировал на видео — 🔥 «жиза»"
    assert (
        reaction_announcement(
            kind="single", media_type="video", count=1, emoji=None, phrase=None
        )
        == "Бот отреагировал на видео"
    )


# --- XP-правило --------------------------------------------------------------

def test_media_reaction_xp_rule_is_limited_per_message():
    rule = game_config.XP_RULES[game_config.EV_MEDIA_REACTION]
    assert rule.points == 3
    # Лимит + дискриминатор-сообщение = «один пост — максимум один раз».
    assert rule.limit == "day"
    assert game_config.EV_MEDIA_REACTION in awards.ALL_EVENTS


# --- запись поста / реакции --------------------------------------------------

class _FakeSession:
    def __init__(self, *, scalar=None) -> None:
        self._scalar = list(scalar or [])
        self.added: list = []
        self.commits = 0

    async def scalar(self, *_a, **_k):
        return self._scalar.pop(0) if self._scalar else None

    async def get(self, _model, _key):
        return None

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_record_post_stores_media_meta(monkeypatch):
    async def _on(_session):
        return True

    monkeypatch.setattr(memes, "is_game_enabled", _on)
    # scalar: PK автора → «такого поста ещё нет».
    session = _FakeSession(scalar=[7, None])
    ok = await memes.record_post(
        session,
        chat_id=-100,
        tg_message_id=555,
        telegram_id=5,
        kind="collection",
        media_type="photo",
        media_count=5,
        preview_file_id="FILEID",
    )
    assert ok is True
    post = session.added[0]
    assert (post.media_type, post.media_count) == ("photo", 5)
    assert post.preview_file_id == "FILEID"


@pytest.mark.asyncio
async def test_record_bot_reaction_marks_post(monkeypatch):
    post = memes.GameMediaPost(
        id=42,
        chat_id=-100,
        tg_message_id=555,
        user_id=7,
        kind="single",
        posted_at=NOW,
        responders=[],
        window_responders=[],
    )
    session = _FakeSession(scalar=[post])
    result = await memes.record_bot_reaction(
        session,
        chat_id=-100,
        tg_message_id=555,
        emoji="🔥",
        phrase=None,
    )
    assert result == (42, 7)
    assert post.reaction_emoji == "🔥"
    assert post.reaction_phrase is None
    assert post.reacted_at is not None


@pytest.mark.asyncio
async def test_record_bot_reaction_without_post_returns_none():
    session = _FakeSession(scalar=[None])
    assert (
        await memes.record_bot_reaction(
            session, chat_id=-100, tg_message_id=1, emoji="🔥", phrase=None
        )
        is None
    )


# --- источник ленты «media» --------------------------------------------------

class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _ExecSession:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    async def execute(self, *_a, **_k):
        return _Rows(self._rows)


def _post(**over) -> memes.GameMediaPost:
    base = dict(
        id=7,
        chat_id=-100,
        tg_message_id=555,
        user_id=3,
        kind="single",
        posted_at=NOW,
        responders=[],
        window_responders=[],
        media_type="photo",
        media_count=1,
        preview_file_id="FILEID",
        reaction_emoji="🔥",
        reaction_phrase=None,
        reacted_at=NOW,
    )
    base.update(over)
    return memes.GameMediaPost(**base)


def _user(uid: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        id=uid,
        display_name=f"u{uid}",
        telegram_id=900 + uid,
        avatar_manual_url=None,
        avatar_url=None,
    )


@pytest.mark.asyncio
async def test_media_items_builds_announcement_with_preview():
    session = _ExecSession([(_post(), _user(3))])
    items = await feed._media_items(session, user_id=None, depth=10)
    assert len(items) == 1
    it = items[0]
    assert it["kind"] == feed.FEED_MEDIA
    assert it["user_id"] == 3
    assert it["text"] == "Бот отреагировал на фото — 🔥"
    assert it["detail"]["post_id"] == 7
    assert it["detail"]["media_type"] == "photo"
    assert it["detail"]["media_count"] == 1
    assert it["detail"]["emoji"] == "🔥"


@pytest.mark.asyncio
async def test_media_items_collection_is_one_record():
    post = _post(kind="collection", media_count=5, reaction_emoji=None,
                 reaction_phrase="Сегодня лучше")
    session = _ExecSession([(post, _user(4))])
    items = await feed._media_items(session, user_id=None, depth=10)
    assert len(items) == 1
    assert items[0]["text"] == (
        "Бот отреагировал на подборку (5 файлов) — «Сегодня лучше»"
    )
    assert items[0]["detail"]["media_count"] == 5


def test_feed_registry_knows_media_kind():
    assert feed.FEED_ICONS[feed.FEED_MEDIA] == "📸"
    assert feed.FEED_TITLES[feed.FEED_MEDIA] == "Реакция на медиа"
    assert feed.FEED_MEDIA in feed.FEED_KIND_ORDER


# --- последний заход (presence) ---------------------------------------------

def test_presence_should_touch_throttles():
    presence.reset_throttle()
    assert presence.should_touch(1, now=100.0) is True
    presence._touched_at[1] = 100.0
    assert presence.should_touch(1, now=100.0 + 1) is False
    assert presence.should_touch(1, now=100.0 + presence.TOUCH_THROTTLE_SEC) is True


@pytest.mark.asyncio
async def test_touch_last_app_seen_writes_profile():
    presence.reset_throttle()
    profile = SimpleNamespace(last_app_seen_at=None)

    class _S:
        async def get(self, _model, _key):
            return profile

        async def commit(self):
            return None

        async def rollback(self):
            return None

    assert await presence.touch_last_app_seen(_S(), 5, moment=NOW) is True
    assert profile.last_app_seen_at == NOW
    # Второй вызов в том же окне — пропуск (троттлинг).
    assert await presence.touch_last_app_seen(_S(), 5, moment=NOW) is False


@pytest.mark.asyncio
async def test_touch_last_app_seen_without_profile_is_noop():
    presence.reset_throttle()

    class _S:
        async def get(self, _model, _key):
            return None

        async def commit(self):  # pragma: no cover — не должно вызываться
            raise AssertionError("без профиля коммитить нечего")

        async def rollback(self):  # pragma: no cover
            raise AssertionError("без профиля откатывать нечего")

    assert await presence.touch_last_app_seen(_S(), 77, moment=NOW) is False


# --- ui.show_last_seen -------------------------------------------------------

@pytest.mark.asyncio
async def test_show_last_seen_default_true_and_toggle(monkeypatch):
    store: dict[str, str] = {}

    async def fake_get(session, key):
        return store.get(key)

    async def fake_set(session, key, value):
        store[key] = value

    monkeypatch.setattr(ac, "_get_value", fake_get)
    monkeypatch.setattr(ac, "_set_value", fake_set)

    # По умолчанию включено у всех (прод-фидбек).
    assert await ac.get_ui_show_last_seen(None, 777) is True
    await ac.set_ui_show_last_seen(None, 777, False)
    assert store["ui.show_last_seen:777"] == "0"
    assert await ac.get_ui_show_last_seen(None, 777) is False
    await ac.set_ui_show_last_seen(None, 777, True)
    assert await ac.get_ui_show_last_seen(None, 777) is True


def test_ui_prefs_patch_carries_show_last_seen():
    from app.api.routes_users import UiPrefsPatch

    assert UiPrefsPatch().show_last_seen is None
    assert UiPrefsPatch(show_last_seen=False).show_last_seen is False
