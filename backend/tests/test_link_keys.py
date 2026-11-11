"""Ключ подписи на организацию: S-10/S-11.

Проверяем ровно то, ради чего меняли схему:

* подпись одной организации не проходит у другой;
* предыдущий ключ работает в окне 30 дней и перестаёт после;
* прежние ссылки на общем ключе продолжают открываться;
* iCal-токен несёт организацию и не подходит чужой.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://semitaskbot.pages.dev")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.test_link_keys.db")

from app.services import hr_media, ical, link_keys  # noqa: E402

ORG_A = b"a" * 32
ORG_B = b"b" * 32


def _activate(keys: link_keys.Keys):
    return link_keys.activate(keys)


def test_media_signature_belongs_to_organization() -> None:
    token = _activate(link_keys.Keys(ORG_A))
    try:
        signature = hr_media.sign("blob", 7)
        assert hr_media.verify("blob", 7, signature) is True
    finally:
        link_keys.deactivate(token)

    # Без контекста проверяется только общий ключ — чужая подпись не проходит.
    assert hr_media.verify("blob", 7, signature) is False

    token = _activate(link_keys.Keys(ORG_B))
    try:
        assert hr_media.verify("blob", 7, signature) is False
    finally:
        link_keys.deactivate(token)


def test_previous_key_works_during_the_window() -> None:
    token = _activate(link_keys.Keys(ORG_A))
    try:
        signature = hr_media.sign("blob", 8)
    finally:
        link_keys.deactivate(token)

    token = _activate(
        link_keys.Keys(
            ORG_B,
            previous=ORG_A,
            previous_until=datetime.now(UTC) + timedelta(days=30),
        )
    )
    try:
        assert hr_media.verify("blob", 8, signature) is True
    finally:
        link_keys.deactivate(token)


def test_previous_key_expires() -> None:
    token = _activate(link_keys.Keys(ORG_A))
    try:
        signature = hr_media.sign("blob", 9)
    finally:
        link_keys.deactivate(token)

    token = _activate(
        link_keys.Keys(
            ORG_B,
            previous=ORG_A,
            previous_until=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    try:
        assert hr_media.verify("blob", 9, signature) is False
    finally:
        link_keys.deactivate(token)


def test_global_signature_still_opens_after_org_key_appears() -> None:
    """Ссылки, выданные до S-11, не должны отвалиться в день выкладки."""
    legacy = hr_media.sign("blob", 10)  # без контекста — общий ключ
    token = _activate(link_keys.Keys(ORG_A))
    try:
        assert hr_media.verify("blob", 10, legacy) is True
    finally:
        link_keys.deactivate(token)


def test_ical_token_carries_the_organization() -> None:
    token = _activate(link_keys.Keys(ORG_A))
    try:
        value = ical.make_token(7, org_id=3)
    finally:
        link_keys.deactivate(token)

    assert value.startswith("3.")
    assert ical.parse_token(value)[0] == 3

    token = _activate(link_keys.Keys(ORG_A))
    try:
        assert ical.verify_token(7, value) is True
    finally:
        link_keys.deactivate(token)

    token = _activate(link_keys.Keys(ORG_B))
    try:
        assert ical.verify_token(7, value) is False
    finally:
        link_keys.deactivate(token)


def test_legacy_ical_token_still_verifies() -> None:
    """Прежний токен без организации считается от общего секрета."""
    legacy = ical.make_token(7)
    assert ical.parse_token(legacy)[0] is None
    assert ical.verify_token(7, legacy) is True
    assert ical.verify_token(8, legacy) is False


def test_rubbish_ical_token_does_not_raise() -> None:
    for bad in ("", "0" * 32, "3.", ".", "3.не-токен", "abc.def"):
        assert ical.verify_token(7, bad) is False


class _FakeSession:
    """Сессия без БД: нужна только для `ensure`/`rotate`."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj: object) -> None:
        return None

    async def flush(self) -> None:
        return None


async def test_ensure_generates_and_saves_key() -> None:
    org = SimpleNamespace(
        media_key=None, media_key_prev=None, media_key_rotated_at=None
    )
    session = _FakeSession()

    await link_keys.ensure(session, org)

    assert org.media_key is not None
    assert len(org.media_key) == 64
    # Без коммита ключ не переживёт GET-запрос, и каждая выдача подпишет
    # ссылку новым ключом — то есть сломает предыдущую.
    assert session.commits == 1


async def test_rotate_moves_current_key_to_previous() -> None:
    old = "a" * 64
    org = SimpleNamespace(
        media_key=old, media_key_prev=None, media_key_rotated_at=None
    )

    rotated_at = await link_keys.rotate(_FakeSession(), org)

    assert org.media_key_prev == old
    assert org.media_key is not None and org.media_key != old
    assert org.media_key_rotated_at == rotated_at
    assert rotated_at.tzinfo is not None


def test_media_kind_and_id_still_matter_with_org_key() -> None:
    token = _activate(link_keys.Keys(ORG_A))
    try:
        signature = hr_media.sign("blob", 11)
        assert hr_media.verify("blob", 12, signature) is False
        assert hr_media.verify("tgphoto", 11, signature) is False
    finally:
        link_keys.deactivate(token)
