"""Тесты для GHG6 PX5: parse_mtproto_blob."""
from __future__ import annotations

from app.services.proxies import parse_mtproto_blob


def test_parse_single_block():
    text = """
    Server: 178.105.137.152
    Port: 443
    Secret: eeabf13064a3bf0851a02ad67114f842ce676f6f676c65617069732e636f6d
    @ProxyMTProto
    """
    drafts = parse_mtproto_blob(text)
    assert len(drafts) == 1
    d = drafts[0]
    assert d.server == "178.105.137.152"
    assert d.port == 443
    assert d.secret and d.secret.startswith("eeabf13064a3bf0851a02ad67114f842")
    assert d.type == "mtproto"


def test_parse_two_blocks_in_one_blob():
    text = """
    Server: 178.105.137.152
    Port: 443
    Secret: eeabf13064a3bf0851a02ad67114f842ce676f6f676c65617069732e636f6d
    @ProxyMTProto

    PROXY MTProto
    Server: mt.nowaboost.com
    Port: 853
    Secret: 4fd95a487c5c87ae82b6639a9b6b5ff2
    @ProxyMTProto
    """
    drafts = parse_mtproto_blob(text)
    assert len(drafts) == 2
    assert drafts[0].server == "178.105.137.152"
    assert drafts[1].server == "mt.nowaboost.com"
    assert drafts[1].port == 853
    assert drafts[1].secret == "4fd95a487c5c87ae82b6639a9b6b5ff2"


def test_parse_equals_separator_and_mixed_case():
    text = "SERVER = 1.2.3.4\nport=8888\nsecret = deadbeef"
    drafts = parse_mtproto_blob(text)
    assert len(drafts) == 1
    assert drafts[0].server == "1.2.3.4"
    assert drafts[0].port == 8888
    assert drafts[0].secret == "deadbeef"


def test_parse_skips_without_port():
    text = "Server: 1.2.3.4\nSecret: deadbeef"
    drafts = parse_mtproto_blob(text)
    assert drafts == []


def test_parse_skips_invalid_port():
    text = "Server: 1.2.3.4\nPort: 99999\nSecret: deadbeef"
    drafts = parse_mtproto_blob(text)
    assert drafts == []


def test_parse_empty_returns_empty():
    assert parse_mtproto_blob("") == []
    assert parse_mtproto_blob("garbage text\nwith no markers") == []


def test_parse_no_secret_ok():
    text = "Server: 1.2.3.4\nPort: 443"
    drafts = parse_mtproto_blob(text)
    assert len(drafts) == 1
    assert drafts[0].secret is None
