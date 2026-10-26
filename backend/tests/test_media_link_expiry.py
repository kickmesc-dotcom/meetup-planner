"""Ссылка на фото с ограниченным сроком: S-11 из аудита 26.10.2026.

Проверяем ровно то, ради чего правили, и ту границу, которую легко сломать:

* ссылка со сроком живёт и открывается до этого срока и перестаёт работать после;
* срок нельзя продлить правкой адреса — он внутри подписи;
* подпись по-прежнему привязана к своему объекту (`blob` ≠ `tgphoto`, чужой id);
* старые ссылки без срока принимаются до объявленной даты и перестают — после;
* с выключенным сроком (`MEDIA_LINK_TTL_DAYS=0`) поведение прежнее, но и это
  проверено, чтобы «выключено» не превращалось в «не работает».
"""

from __future__ import annotations

import importlib
import os
import time
from datetime import UTC, datetime, timedelta

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://semitaskbot.pages.dev")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.test_media_expiry.db")

import pytest  # noqa: E402

from app.services import hr_media  # noqa: E402

DAY = 86400


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MEDIA_LINK_TTL_DAYS", raising=False)
    monkeypatch.delenv("MEDIA_LEGACY_SIG_UNTIL", raising=False)
    yield


def test_fresh_link_verifies():
    signature = hr_media.sign("blob", 17)
    assert hr_media.verify("blob", 17, signature) is True


def test_link_has_expiry_inside_the_signature():
    """Формат — `<срок>.<hmac>`: срок часть подписи, а не отдельный параметр."""
    expires_raw, _, mac = hr_media.sign("blob", 17).partition(".")
    assert expires_raw.isdigit(), "срок должен быть в самой подписи"
    assert int(expires_raw) > time.time(), "срок должен быть в будущем"
    assert len(mac) == 32


def test_expired_link_is_rejected():
    past = int(time.time() - DAY)
    assert hr_media.verify("blob", 17, hr_media.sign("blob", 17, expires=past)) is False


def test_expiry_cannot_be_extended_by_editing_the_url():
    """Главное: продлить срок правкой адреса нельзя — подпись не сойдётся."""
    signature = hr_media.sign("blob", 17, expires=int(time.time() - DAY))
    _, _, mac = signature.partition(".")
    forged_future = f"{int(time.time() + 10 * DAY)}.{mac}"
    assert hr_media.verify("blob", 17, forged_future) is False


def test_signature_is_bound_to_kind_and_id():
    signature = hr_media.sign("blob", 17)
    assert hr_media.verify("blob", 18, signature) is False
    assert hr_media.verify("tgphoto", 17, signature) is False
    assert hr_media.verify("blob", 17, "") is False
    assert hr_media.verify("blob", 17, None) is False


def test_rubbish_signature_does_not_raise():
    for bad in ("нет-точек", "abc.def", "12.", ".", "12.a" * 20):
        assert hr_media.verify("blob", 17, bad) is False


def test_same_day_gives_the_same_url():
    """Адрес стабилен внутри суток: иначе перестал бы работать кэш края Cloudflare."""
    assert hr_media.sign("blob", 17) == hr_media.sign("blob", 17)


def test_urls_carry_the_expiring_signature():
    expires_raw, _, _ = hr_media.url_for(5).split("s=")[1].partition(".")
    assert expires_raw.isdigit()
    expires_raw, _, _ = hr_media.photo_url(6).split("s=")[1].partition(".")
    assert expires_raw.isdigit()


def test_legacy_signature_accepted_until_the_stated_date():
    legacy = hr_media._legacy_sign("blob", 17)  # noqa: SLF001 — проверяем совместимость
    assert hr_media.verify("blob", 17, legacy) is True


def test_legacy_signature_is_refused_after_the_window(monkeypatch: pytest.MonkeyPatch):
    legacy = hr_media._legacy_sign("blob", 17)  # noqa: SLF001
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    monkeypatch.setenv("MEDIA_LEGACY_SIG_UNTIL", yesterday)
    assert hr_media.verify("blob", 17, legacy) is False, (
        "окно совместимости должно закрываться, иначе оно вечное"
    )


def test_legacy_signature_refused_when_window_is_off(monkeypatch: pytest.MonkeyPatch):
    legacy = hr_media._legacy_sign("blob", 17)  # noqa: SLF001
    monkeypatch.setenv("MEDIA_LEGACY_SIG_UNTIL", "off")
    assert hr_media.verify("blob", 17, legacy) is False


def test_changing_the_bot_token_invalidates_links(monkeypatch: pytest.MonkeyPatch):
    """Ключ подписи — токен бота: его смена отзывает все ссылки (аварийный отзыв)."""
    signature = hr_media.sign("blob", 17)
    monkeypatch.setenv("BOT_TOKEN", "another-token")
    from app.config import get_settings

    get_settings.cache_clear()
    hr_media_reloaded = importlib.reload(hr_media)
    try:
        assert hr_media_reloaded.verify("blob", 17, signature) is False
    finally:
        get_settings.cache_clear()
        monkeypatch.undo()
        importlib.reload(hr_media)


def test_ttl_can_be_turned_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEDIA_LINK_TTL_DAYS", "0")
    signature = hr_media.sign("blob", 17)
    assert signature.startswith("0.")
    assert hr_media.verify("blob", 17, signature) is True


def test_ttl_days_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEDIA_LINK_TTL_DAYS", "3")
    assert hr_media.link_ttl_days() == 3
    expires = int(hr_media.sign("blob", 17).partition(".")[0])
    assert time.time() < expires <= time.time() + 3 * DAY
    # Округление вниз до суток: адрес не меняется в течение дня.
    assert expires % DAY == 0
