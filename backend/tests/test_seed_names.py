"""Сид — заготовка, а не переименователь.

Регресс из раунда 5: миграция `0050` переименовала владельца в «Сергей», но
`seed_users` на каждом старте возвращал ник из `WHITELIST_NAMES`, и в профиле
снова появлялось «Серж-NEO». Здесь закреплено правило: имя существующего
человека сид не трогает, цвет — может (он оформительский).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.db import seed as seed_module


class _Session:
    """Минимальная заглушка сессии: только то, что использует `seed_users`."""

    def __init__(self, existing: SimpleNamespace) -> None:
        self.existing = existing
        self.added: list[object] = []
        self.commits = 0

    async def scalar(self, _stmt: object) -> SimpleNamespace:
        return self.existing

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def _run(monkeypatch, *, existing: SimpleNamespace) -> _Session:
    monkeypatch.setattr(
        seed_module,
        "get_settings",
        lambda: SimpleNamespace(whitelist_pairs=[(306733739, "Сергей")]),
    )
    session = _Session(existing)
    asyncio.run(seed_module.seed_users(session))  # type: ignore[arg-type]
    return session


def test_seed_does_not_rename_existing_user(monkeypatch):
    user = SimpleNamespace(telegram_id=306733739, display_name="Серж-NEO", color_hex="#000000")
    _run(monkeypatch, existing=user)

    # Имя осталось тем, что стоит в базе (или что человек выбрал сам).
    assert user.display_name == "Серж-NEO"


def test_seed_still_aligns_color(monkeypatch):
    user = SimpleNamespace(telegram_id=306733739, display_name="Своё имя", color_hex="#000000")
    session = _run(monkeypatch, existing=user)

    assert user.color_hex != "#000000"
    assert session.commits >= 1


def test_seed_does_not_add_duplicate_for_existing(monkeypatch):
    user = SimpleNamespace(telegram_id=306733739, display_name="Сергей", color_hex="#22c55e")
    session = _run(monkeypatch, existing=user)

    assert session.added == []
