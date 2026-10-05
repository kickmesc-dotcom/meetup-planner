"""GHG11(4): тексты фич, целевые вкладки анонсов и вид ленты.

Без БД: проверяем чистую часть — переименование редакторов фраз, мэппинг
«кнопки Открыть» из анонса фичи и дефолт компактного вида ленты.
"""
from __future__ import annotations

from app.services.game import config


def test_phrases_editors_renamed_to_shared_pools():
    assert config.feature_title("loser_phrases_editor") == "Редактор шаблонов фраз лоха ✍️"
    assert (
        config.feature_title("chukhan_phrases_editor")
        == "Редактор шаблонов фраз чухана ✍️"
    )
    # Описание прямо говорит, что правится ОБЩИЙ набор, а не свой список.
    assert "ОБЩИЙ" in config.feature_description("loser_phrases_editor")
    assert "ОБЩИЙ" in config.feature_description("chukhan_phrases_editor")


def test_every_unlockable_feature_has_a_target():
    """У каждой фичи из разблокировок есть (вкладка, якорь) для кнопки «Открыть»."""
    codes = {c for codes in config.LEVEL_UNLOCKS.values() for c in codes}
    for code in codes:
        tab, _anchor = config.feature_target(code)
        assert tab in {"feed", "calendar", "meetings", "profile", "admin"}, code


def test_unknown_feature_target_is_empty():
    assert config.feature_target("nope") == ("", "")


def test_phrases_editors_point_at_admin_tab():
    # Редакторы фраз лоха/чухана живут в админке.
    assert config.feature_target("loser_phrases_editor")[0] == "admin"
    assert config.feature_target("chukhan_phrases_editor")[0] == "admin"
