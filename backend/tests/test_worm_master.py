"""GHG8 T3.6: тесты чистого ядра режима «червь-господин» (без БД/aiogram).

Покрывает choose (сырой выбор + пустой пул + взвешивание), render (подстановка
{username}/{target}/{chance}, безопасность к чужим «{...}»), build_announce_extra
и pick_nag. Поведенческие части (инъекция в анонсы, /punish, поддакивание)
тестируются в своих подэтапах.
"""
from __future__ import annotations

from app.services.worm_master import (
    DEFAULT_WORM_ANNOUNCE_LINES,
    DEFAULT_WORM_MASTER_AGREES,
    DEFAULT_WORM_MASTER_NAG,
    DEFAULT_WORM_MASTER_PREFIXES,
    DEFAULT_WORM_MASTER_SUFFIXES,
    DEFAULT_WORM_PUNISH_PHRASES,
    build_announce_extra,
    choose,
    extract_punish_target,
    pick_nag,
    render,
    text_has_punish_hashtag,
)


# --- choose: сырой выбор без подстановки ---

def test_choose_returns_raw_member():
    pool = ["раз {username}", "два", "три"]
    for _ in range(20):
        assert choose(pool) in pool


def test_choose_empty_pool_is_none():
    assert choose([]) is None
    assert choose(None) is None
    assert choose(["", "  ", "\t"]) is None


def test_choose_skips_blank_entries():
    assert choose(["", "  ", "только эта"]) == "только эта"


def test_choose_does_not_substitute():
    # choose возвращает СЫРУЮ фразу — плейсхолдер должен остаться (его хэш =
    # ключ в use_counts, инкремент идёт по сырой фразе).
    assert choose(["привет {username}"]) == "привет {username}"


def test_choose_weighted_prefers_unused():
    from app.services.phrase_weights import phrase_hash

    pool = ["часто", "редко"]
    # «часто» уже использована 100 раз → вес ~1/101, «редко» — вес 1.0.
    use_counts = {phrase_hash("часто"): 100}
    picks = [choose(pool, use_counts) for _ in range(200)]
    assert picks.count("редко") > picks.count("часто")


# --- render: подстановка плейсхолдеров ---

def test_render_substitutes_username_and_target():
    assert render("слуга {username}", username="Серж") == "слуга Серж"
    assert render("бью {target}", target="@kos") == "бью @kos"


def test_render_substitutes_chance():
    assert render("шанс {chance}%", chance_pct="1.0") == "шанс 1.0%"


def test_render_leaves_unknown_placeholders_intact():
    # чужая «{foo}» в кастомной фразе не должна ронять генерацию
    assert render("{foo} и {username}", username="Х") == "{foo} и Х"


def test_render_no_value_keeps_placeholder():
    # значение не передано → плейсхолдер не трогаем
    assert render("{username} тут", target="@a") == "{username} тут"


# --- build_announce_extra ---

def test_build_announce_extra_joins_and_substitutes():
    lines = ["Господин {username}.", "Шанс был {chance}%."]
    out = build_announce_extra(lines, username="Митя", chance_pct="5")
    assert out == "Господин Митя.\nШанс был 5%."


def test_build_announce_extra_empty_is_none():
    assert build_announce_extra([], username="Х", chance_pct="1") is None
    assert build_announce_extra(None, username="Х", chance_pct="1") is None


# --- pick_nag ---

def test_pick_nag_substitutes_and_picks_member():
    out = pick_nag(["отстань {username}"], username="Лорд")
    assert out == "отстань Лорд"


def test_pick_nag_empty_is_none():
    assert pick_nag([], username="Х") is None


# --- дефолтные пулы ---

def test_default_pools_nonempty_strings():
    pools = [
        DEFAULT_WORM_MASTER_PREFIXES,
        DEFAULT_WORM_MASTER_SUFFIXES,
        DEFAULT_WORM_MASTER_AGREES,
        DEFAULT_WORM_MASTER_NAG,
        DEFAULT_WORM_PUNISH_PHRASES,
        DEFAULT_WORM_ANNOUNCE_LINES,
    ]
    for pool in pools:
        assert pool, "пул не должен быть пустым"
        assert all(isinstance(p, str) and p.strip() for p in pool)


def test_default_punish_pool_has_target_placeholder():
    # каждая punish-фраза должна уметь упомянуть жертву
    assert all("{target}" in p for p in DEFAULT_WORM_PUNISH_PHRASES)


def test_default_punish_pool_size():
    # пользователь просил «порядка 20»
    assert len(DEFAULT_WORM_PUNISH_PHRASES) >= 15


# --- /punish: хештег-триггер и разбор цели ---

def test_punish_hashtag_detects_both_variants():
    assert text_has_punish_hashtag("эй #punish @kos")
    assert text_has_punish_hashtag("а ну #наказать его")
    assert text_has_punish_hashtag("#PUNISH регистр")


def test_punish_hashtag_negative():
    assert not text_has_punish_hashtag("просто текст")
    assert not text_has_punish_hashtag("#punisher не тот тег")  # \b граница
    assert not text_has_punish_hashtag(None)


def test_extract_target_prefers_at_mention():
    assert extract_punish_target("/punish @serge") == "@serge"
    assert extract_punish_target("#наказать @kos за всё") == "@kos"


def test_extract_target_fallback_first_token_after_command():
    # без @ — берём первое значимое слово после команды
    assert extract_punish_target("/punish Серж") == "Серж"
    assert extract_punish_target("#punish Митя") == "Митя"


def test_extract_target_none_when_empty():
    assert extract_punish_target("/punish") is None
    assert extract_punish_target("#наказать") is None
    assert extract_punish_target(None) is None


def test_render_punish_substitutes_target():
    raw = choose(["бью {target} с ноги"])
    assert render(raw, target="@kos") == "бью @kos с ноги"
