from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


@dataclass(frozen=True)
class InitDataPayload:
    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    auth_date: int
    raw: dict[str, str]


class InitDataError(Exception):
    pass


def parse_and_verify(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> InitDataPayload:
    """
    Validates Telegram WebApp initData per
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Algorithm:
        secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
        data_check_string = "\\n".join(f"{k}={v}" for k,v in sorted(items if k != "hash"))
        expected = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
        require expected == hash AND now - auth_date <= max_age_seconds
    """
    if not init_data:
        raise InitDataError("empty initData")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        raise InitDataError("hash mismatch")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("auth_date not int") from exc

    if auth_date <= 0:
        raise InitDataError("auth_date missing")
    if time.time() - auth_date > max_age_seconds:
        raise InitDataError("initData expired")

    user_json = pairs.get("user")
    if not user_json:
        raise InitDataError("missing user")
    try:
        user = json.loads(user_json)
    except json.JSONDecodeError as exc:
        raise InitDataError("user not json") from exc

    user_id = user.get("id")
    if not isinstance(user_id, int):
        raise InitDataError("user.id missing")

    return InitDataPayload(
        user_id=user_id,
        username=user.get("username"),
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        auth_date=auth_date,
        raw=pairs,
    )
