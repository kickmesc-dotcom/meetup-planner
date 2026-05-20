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


def test_parse_tg_proxy_url():
    text = "Подключайся: tg://proxy?server=1.2.3.4&port=443&secret=deadbeef"
    drafts = parse_mtproto_blob(text)
    assert len(drafts) == 1
    assert drafts[0].server == "1.2.3.4"
    assert drafts[0].port == 443
    assert drafts[0].secret == "deadbeef"
    assert drafts[0].type == "mtproto"


def test_parse_t_me_proxy_url():
    text = "https://t.me/proxy?server=mt.host.com&port=443&secret=ee00ff"
    drafts = parse_mtproto_blob(text)
    assert len(drafts) == 1
    assert drafts[0].type == "mtproto"
    assert drafts[0].server == "mt.host.com"


def test_parse_socks_url_marks_type():
    text = "tg://socks?server=1.2.3.4&port=1080&user=u&pass=p"
    drafts = parse_mtproto_blob(text)
    assert len(drafts) == 1
    assert drafts[0].type == "socks5"


def test_parse_kv_type_hint_in_header():
    text = """SOCKS5 proxy
    Server: 9.9.9.9
    Port: 1080
    """
    drafts = parse_mtproto_blob(text)
    assert len(drafts) == 1
    assert drafts[0].type == "socks5"


def test_parse_dedupes_same_server_port():
    text = """tg://proxy?server=1.2.3.4&port=443&secret=aa
    Server: 1.2.3.4
    Port: 443
    Secret: bb
    """
    drafts = parse_mtproto_blob(text)
    assert len(drafts) == 1  # дубликат отброшен — оба раза (1.2.3.4, 443)


def test_parse_url_and_kv_block_mixed():
    text = """Forward by @ProxyMTProto
    tg://proxy?server=1.1.1.1&port=443&secret=aaaa

    Server: 2.2.2.2
    Port: 443
    Secret: bbbb
    @ProxyMTProto
    """
    drafts = parse_mtproto_blob(text)
    assert len(drafts) == 2
    servers = sorted(d.server for d in drafts)
    assert servers == ["1.1.1.1", "2.2.2.2"]
