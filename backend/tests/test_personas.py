"""GHG8 P6 — генератор фраз v2 «с типажами».

Async-БД-стенда нет — тестируем чистое: parse_persona (секции/слоты/мусор),
render_phrase (заполнение слотов, отбраковка битых шаблонов, пунктуация),
weighted_pick_user (вес активности, базовый вес молчунов), версия генератора
(константы + pydantic-pattern GeneratorSettings*).
"""
from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from app.api.routes_admin import GeneratorSettingsOut, GeneratorSettingsUpdate
from app.services.admin_config import (
    PHRASE_GENERATOR_VERSIONS,
    _PHRASE_GENERATOR_VERSION_DEFAULT,
)
from app.services.personas import (
    BASE_ACTIVITY_WEIGHT,
    parse_persona,
    render_phrase,
    weighted_pick_user,
)


# --- parse_persona ---

def test_parse_empty_and_none():
    assert not parse_persona(None).is_usable
    assert not parse_persona("").is_usable
    assert not parse_persona("просто текст без секций").is_usable


def test_parse_templates_and_slots():
    p = parse_persona(
        "[шаблоны]\n"
        "Я блять ненавижу {объект}\n"
        "Готовая фраза без слотов\n"
        "[объект]\n"
        "индусов\n"
        "понедельники\n"
    )
    assert p.is_usable
    assert len(p.templates) == 2
    assert p.slots["объект"] == ["индусов", "понедельники"]


def test_parse_skips_comments_blank_and_preamble():
    p = parse_persona(
        "преамбула до секций — игнор\n"
        "\n"
        "[шаблоны]\n"
        "# комментарий\n"
        "  Фраза с отступом  \n"
        "\n"
        "[слот]\n"
        "значение\n"
    )
    assert p.templates == ["Фраза с отступом"]
    assert p.slots == {"слот": ["значение"]}


def test_parse_section_names_case_insensitive():
    p = parse_persona("[ШАБЛОНЫ]\nфраза\n[Объект]\nх\n")
    assert p.templates == ["фраза"]
    assert "объект" in p.slots


# --- render_phrase ---

def test_render_no_usable_templates_returns_none():
    # Единственный шаблон ссылается на пустой слот → отбрасывается.
    p = parse_persona("[шаблоны]\nненавижу {объект}\n")
    assert render_phrase(p) is None


def test_render_fills_slots_deterministic():
    p = parse_persona("[шаблоны]\nненавижу {объект}\n[объект]\nиндусов\n")
    out = render_phrase(p, random.Random(1))
    assert out == "ненавижу индусов."


def test_render_appends_period_only_when_missing():
    p1 = parse_persona("[шаблоны]\nуже с точкой.\n")
    assert render_phrase(p1) == "уже с точкой."
    p2 = parse_persona("[шаблоны]\nс воплем!\n")
    assert render_phrase(p2) == "с воплем!"


def test_render_multiple_placeholders_same_slot():
    p = parse_persona("[шаблоны]\n{х} и {х}\n[х]\nа\n")
    assert render_phrase(p) == "а и а."


def test_render_broken_template_skipped_good_one_used():
    p = parse_persona(
        "[шаблоны]\nбитый {нет_такого}\nгодный {объект}\n[объект]\nх\n"
    )
    for seed in range(10):
        assert render_phrase(p, random.Random(seed)) == "годный х."


# --- weighted_pick_user ---

def test_pick_empty_candidates_none():
    assert weighted_pick_user({1: 100}, []) is None


def test_pick_single_candidate():
    assert weighted_pick_user({}, [42]) == 42


def test_pick_silent_user_still_possible():
    # Молчун (0 сообщений) имеет вес BASE_ACTIVITY_WEIGHT > 0 — выпадает.
    assert BASE_ACTIVITY_WEIGHT > 0
    rng = random.Random(7)
    picks = {weighted_pick_user({1: 5}, [1, 2], rng) for _ in range(200)}
    assert picks == {1, 2}


def test_pick_activity_skews_distribution():
    rng = random.Random(3)
    counts = {1: 0, 2: 0}
    for _ in range(500):
        counts[weighted_pick_user({1: 99, 2: 0}, [1, 2], rng)] += 1
    assert counts[1] > counts[2] * 5  # 100:1 по весам — перекос явный


# --- P6.3: версия генератора ---

def test_generator_versions_and_default():
    assert set(PHRASE_GENERATOR_VERSIONS) == {"legacy", "personas"}
    assert _PHRASE_GENERATOR_VERSION_DEFAULT == "legacy"


@pytest.mark.parametrize("v", ["legacy", "personas"])
def test_generator_settings_accepts_valid_version(v):
    out = GeneratorSettingsOut(
        count_min=2, count_max=6, lookback_days=7,
        collective_chance=0.1, user_chance=1.0, generator_version=v,
    )
    assert out.generator_version == v


def test_generator_settings_rejects_invalid_version():
    with pytest.raises(ValidationError):
        GeneratorSettingsUpdate(
            count_min=2, count_max=6, lookback_days=7,
            collective_chance=0.1, user_chance=1.0, generator_version="llm",
        )


def test_generator_settings_default_is_legacy():
    # Старые клиенты не присылают поле — совместимость.
    body = GeneratorSettingsUpdate(
        count_min=2, count_max=6, lookback_days=7,
        collective_chance=0.1, user_chance=1.0,
    )
    assert body.generator_version == "legacy"
