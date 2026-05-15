from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.auth.initdata import InitDataError, parse_and_verify

BOT_TOKEN = "12345:test-token"


def _sign(params: dict[str, str], token: str = BOT_TOKEN) -> str:
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def _make_init_data(user_id: int = 42, age_seconds: int = 0, token: str = BOT_TOKEN) -> str:
    user = {"id": user_id, "first_name": "Test", "username": "tester"}
    params = {
        "auth_date": str(int(time.time()) - age_seconds),
        "query_id": "qid",
        "user": json.dumps(user, separators=(",", ":")),
    }
    params["hash"] = _sign(params, token)
    return urlencode(params)


def test_valid_initdata_passes() -> None:
    init = _make_init_data(user_id=42)
    payload = parse_and_verify(init, BOT_TOKEN)
    assert payload.user_id == 42
    assert payload.username == "tester"


def test_tampered_hash_rejected() -> None:
    init = _make_init_data(user_id=42)
    bad = init.replace("Test", "Hack")
    with pytest.raises(InitDataError):
        parse_and_verify(bad, BOT_TOKEN)


def test_wrong_token_rejected() -> None:
    init = _make_init_data(user_id=42, token="other:token")
    with pytest.raises(InitDataError):
        parse_and_verify(init, BOT_TOKEN)


def test_expired_initdata_rejected() -> None:
    init = _make_init_data(age_seconds=86400 + 60)
    with pytest.raises(InitDataError, match="expired"):
        parse_and_verify(init, BOT_TOKEN)


def test_missing_hash_rejected() -> None:
    with pytest.raises(InitDataError, match="missing hash"):
        parse_and_verify("auth_date=123&user=%7B%22id%22%3A1%7D", BOT_TOKEN)


def test_empty_rejected() -> None:
    with pytest.raises(InitDataError):
        parse_and_verify("", BOT_TOKEN)
