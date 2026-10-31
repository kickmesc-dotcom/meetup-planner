"""Кто получает права редактора. Env — для владельцев продукта, не для клиентов.

Почему это отдельный тест. На проде `ADMIN_TG_IDS` и `WHITELIST_TG_IDS` совпадали,
и `staff_tg_id_set` склеивал их в один набор: каждый, кого вписали в список
«люди проекта», автоматически получал кабинет управления. Для клиентской
команды это неверно — её управляющие приходят из приглашения, а не из env.

Правило, которое здесь закреплено:

* `ADMIN_TG_IDS` (и встроенная пара) → admin на пустой базе, это бутстрап;
* `WHITELIST_TG_IDS` → ничего, кроме «человек известен сиду»;
* членство в организации → owner = admin, manager = aup, staff = employee.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from app import config  # noqa: E402
from app.services import hr_access  # noqa: E402


def _settings(monkeypatch, *, admins: str, whitelist: str):
    monkeypatch.setenv("ADMIN_TG_IDS", admins)
    monkeypatch.setenv("WHITELIST_TG_IDS", whitelist)
    config.get_settings.cache_clear()
    return config.get_settings()


def test_whitelist_no_longer_grants_admin(monkeypatch):
    settings = _settings(
        monkeypatch,
        admins="306733739,397594558",
        whitelist="52765607,175773775,380170615,137348534",
    )
    try:
        # Двое владельцев — админы.
        assert 306733739 in settings.staff_tg_id_set
        assert 397594558 in settings.staff_tg_id_set
        # Остальные четверо — нет, хотя они и в списке проекта.
        for outsider in (52765607, 175773775, 380170615, 137348534):
            assert outsider not in settings.staff_tg_id_set
            assert hr_access.default_role_for(outsider) == "employee"
    finally:
        config.get_settings.cache_clear()


def test_org_roles_map_to_hr_roles():
    """Клиент получает права из организации — одинаково для TG и для почты."""
    assert hr_access.hr_role_for_org("owner") == "admin"
    assert hr_access.hr_role_for_org("manager") == "aup"
    assert hr_access.hr_role_for_org("staff") == "employee"
    # Незнакомый уровень не должен случайно дать управление.
    assert hr_access.hr_role_for_org("something-else") == "employee"
