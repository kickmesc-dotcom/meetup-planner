"""Тестовый пул `[BOT]`, плашки и пул доступа владельцев.

Проверяем то, что можно проверить без Postgres: правила именования пула,
синтетические телеграм-ID, состав встроенного пула доступа, соответствие
«владельцы ↔ админы» и подпись плашки в боте. Сами запросы (заведение пула,
симуляция смен, удаление следов) требуют живой базы — нарочно не подменяем их
фейками, чтобы не создать ложного ощущения проверенности.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from app.bot.handlers import hr_bot  # noqa: E402
from app.config import BUILTIN_ADMIN_TG_IDS, get_settings  # noqa: E402
from app.db.hr_models import ROLE_ADMIN, Employee  # noqa: E402
from app.db.hr_seed import OWNERS  # noqa: E402
from app.services import hr_demo, hr_settings  # noqa: E402

OWNER_DEV = 306733739
OWNER_MANAGER = 397594558


# --------------------------------------------------------------------------
# Пул доступа
# --------------------------------------------------------------------------


def test_both_owners_are_admins_by_default():
    """Разработчик и управляющий — админы даже с пустым `ADMIN_TG_IDS` в env."""
    admins = get_settings().admin_tg_id_set
    assert {OWNER_DEV, OWNER_MANAGER} <= admins


def test_owner_seed_matches_access_pool():
    """Сид владельцев и пул доступа не должны разъезжаться."""
    seeded = {tg_id for tg_id, _name, _emoji, _badge in OWNERS}
    assert seeded == set(BUILTIN_ADMIN_TG_IDS)


def test_owners_have_badges():
    """У каждого владельца есть непустая плашка и эмодзи — иначе подпись пустая."""
    for _tg_id, name, emoji, badge in OWNERS:
        assert name and badge and emoji


# --------------------------------------------------------------------------
# Плашка должность/звание
# --------------------------------------------------------------------------


def _employee(**kwargs: object) -> Employee:
    return Employee(id=1, user_id=1, **kwargs)  # type: ignore[arg-type]


def test_badge_text_includes_emoji_and_title():
    text = hr_bot.badge_text(_employee(badge="Разработчик", badge_emoji="🛠"))
    assert "Разработчик" in text
    assert "🛠" in text


def test_badge_text_is_empty_without_badge():
    assert hr_bot.badge_text(_employee()) == ""


def test_badge_text_survives_missing_emoji():
    """Плашку могли завести без значка — текст всё равно должен появиться."""
    text = hr_bot.badge_text(_employee(badge="Управляющий"))
    assert "Управляющий" in text


def test_demo_mark_only_for_demo_employees():
    assert hr_demo.DEMO_PREFIX in hr_bot.demo_mark(_employee(is_demo=True))
    assert hr_bot.demo_mark(_employee(is_demo=False)) == ""


# --------------------------------------------------------------------------
# Тестовый пул `[BOT]`
# --------------------------------------------------------------------------


def test_demo_names_carry_prefix():
    name = hr_demo.demo_display_name("Алина")
    assert hr_demo.is_demo_name(name)
    assert not hr_demo.is_demo_name("Сергей")


def test_demo_rename_keeps_marker():
    """Правка имени в админке не срезает `[BOT]`: метка — инвариант пула."""
    assert hr_demo.demo_title("Алина") == f"{hr_demo.DEMO_PREFIX} Алина"
    # Имя уже с префиксом — второй раз его не добавляем.
    once = hr_demo.demo_title("Алина")
    assert hr_demo.demo_title(once) == once
    # Пробелы и пустое имя не ломают метку.
    assert hr_demo.demo_title(f"  {hr_demo.DEMO_PREFIX}   Борис ") == (
        f"{hr_demo.DEMO_PREFIX} Борис"
    )


def test_demo_telegram_ids_are_synthetic():
    """Синтетическая база выше любых настоящих аккаунтов TG."""
    first = hr_demo.demo_telegram_id(0)
    assert first == hr_demo.DEMO_TG_BASE
    assert hr_demo.is_demo_telegram_id(first)
    # Настоящие id (включая владельцев) никогда не попадают в пул.
    for real_id in (OWNER_DEV, OWNER_MANAGER, 1):
        assert not hr_demo.is_demo_telegram_id(real_id)


def test_demo_ids_are_unique_and_grow_with_index():
    ids = [hr_demo.demo_telegram_id(i) for i in range(hr_demo.demo_pool_size())]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids)


# --------------------------------------------------------------------------
# Тумблер видимости (настройки)
# --------------------------------------------------------------------------


def test_demo_visibility_is_a_known_setting():
    """Тумблер пула — часть тех же HR-правил, что читает админка.

    Ключ и дефолт живут в `hr_settings`, поэтому проверяем именно их: иначе
    ручка админки писала бы в один ключ, а фильтр ленты читал другой.
    """
    assert hr_settings.KEY_DEMO_VISIBLE == "hr.demo.visible"
    assert hr_settings.DEFAULT_DEMO_VISIBLE is True


def test_demo_pool_is_visible_by_default():
    """Пока админ не выключил тумблер, `hidden_employee_ids` ничего не прячет."""
    assert hr_settings.DEFAULT_DEMO_VISIBLE is True


def test_admin_role_constant_is_admin():
    """Роль, которую получают владельцы при сиде."""
    assert ROLE_ADMIN == "admin"
