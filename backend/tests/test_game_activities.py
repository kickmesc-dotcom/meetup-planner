"""Э21: активности в мини-аппе — разбор вариантов и подписи каталога.

Чистая логика (её и проверяем): как ответы промпта превращаются в кнопки и
«нужен ли свободный ввод», и что каталог вообще проставляет подписи.
"""
from __future__ import annotations

from app.api.routes_game import _activity_options
from app.services.game import events_catalog


def test_labeled_answers_become_buttons():
    options, needs_text = _activity_options(
        [
            {"matcher": r"^да$", "xp": 10, "label": "да", "media": False},
            {"matcher": r"^нет$", "xp": 50, "label": "нет", "media": False},
        ]
    )
    assert [o.label for o in options] == ["да", "нет"]
    assert [o.xp for o in options] == [10, 50]
    assert needs_text is False


def test_unlabeled_answer_requires_text():
    options, needs_text = _activity_options(
        [{"matcher": r"^.{12,}$", "xp": 30, "label": None, "media": False}]
    )
    assert options == []
    assert needs_text is True


def test_media_only_answer_still_offers_text_input():
    # Медиа-ответ (мем) в апп не пришлёшь, но ссылку — можно: даём поле ввода.
    options, needs_text = _activity_options(
        [{"matcher": r".*", "xp": 50, "label": None, "media": True}]
    )
    assert options == []
    assert needs_text is True


def test_serialize_answers_keeps_label():
    prompt = events_catalog.PROMPTS_BY_CODE["mom_love"]
    answers = events_catalog.serialize_answers(prompt)
    labels = [a["label"] for a in answers]
    assert labels == ["да", "нет"]


def test_no_answer_data_falls_back_to_text():
    options, needs_text = _activity_options([])
    assert options == []
    assert needs_text is True
