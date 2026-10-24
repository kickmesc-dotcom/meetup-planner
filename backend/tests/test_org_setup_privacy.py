"""Настройка организации и приватность карточки коллеги.

Проверяем чистые правила: что мастер принимает и отбрасывает, как политика
руководства ограничивает личные тумблеры и кто видит чужую активность. Это
те места, где ошибка тихо становится утечкой: «галочку выключили, а данные
всё равно пришли».
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.hr_models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    Employee,
)
from app.db.models import AdminConfig  # noqa: E402
from app.services import hr_profile, org_setup  # noqa: E402


def _person(
    employee_id: int,
    role: str = ROLE_EMPLOYEE,
    department_id: int | None = 1,
    *,
    profile_public: bool = True,
) -> Employee:
    return Employee(
        id=employee_id,
        user_id=employee_id,
        role=role,
        department_id=department_id,
        profile_public=profile_public,
    )


# --------------------------------------------------------------------------
# Мастер организации
# --------------------------------------------------------------------------


def test_master_ignores_unknown_sections_and_keeps_order():
    setup = org_setup.apply_answers(
        org_setup.OrgSetup(), sections=["team", "nonsense", "shifts"]
    )
    assert setup.sections == ("shifts", "team")


def test_master_clamps_unknown_answers_instead_of_storing_garbage():
    setup = org_setup.apply_answers(
        org_setup.OrgSetup(), industry="spaceship", headcount="42"
    )
    assert setup.industry == "restaurant"
    assert setup.headcount == "10_30"


def test_master_cleans_departments_and_drops_duplicates():
    setup = org_setup.apply_answers(
        org_setup.OrgSetup(),
        departments=["  Кухня ", "Кухня", "", "Бар"],
    )
    assert setup.departments == ("Кухня", "Бар")


def test_master_can_change_one_answer_without_resetting_others():
    """Повторный проход не должен затирать уже настроенное."""
    first = org_setup.apply_answers(
        org_setup.OrgSetup(),
        industry="salon",
        sections=["team", "shifts"],
        profile_visibility="managers",
    )
    second = org_setup.apply_answers(first, allow_hide_media=False)
    assert second.industry == "salon"
    assert second.sections == ("shifts", "team")
    assert second.profile_visibility == "managers"
    assert second.allow_hide_media is False


def test_master_rejects_unknown_visibility():
    setup = org_setup.apply_answers(
        org_setup.OrgSetup(), profile_visibility="everyone_forever"  # type: ignore[arg-type]
    )
    assert setup.profile_visibility == "colleagues"


def test_presets_follow_industry_and_always_have_a_fallback():
    kitchen = [item["name"] for item in org_setup.presets_for("restaurant")]
    assert "Кухня" in kitchen
    fallback = org_setup.presets_for("unknown-industry")
    assert fallback  # никогда не пусто: иначе шаг мастера «зависнет»


# --------------------------------------------------------------------------
# Хранение настройки
# --------------------------------------------------------------------------


@pytest.fixture
async def org_session():
    """Мини-стенд: только таблица `admin_config` (её и трогает сервис)."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: AdminConfig.__table__.create(sync_conn))
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
    await engine.dispose()


async def test_setup_defaults_to_working_config(org_session):
    setup = await org_setup.load(org_session)
    assert setup.done is False
    assert setup.profile_visibility == "colleagues"
    assert setup.sections == org_setup.DEFAULT_SECTIONS


async def test_setup_round_trips_through_admin_config(org_session):
    saved = await org_setup.save(
        org_session,
        org_setup.apply_answers(
            org_setup.OrgSetup(),
            industry="cafe",
            departments=["Бариста"],
            sections=["shifts"],
            profile_visibility="managers",
            allow_hide_media=False,
            done=True,
        ),
    )
    assert saved.done is True

    again = await org_setup.load(org_session)
    assert again.industry == "cafe"
    assert again.departments == ("Бариста",)
    assert again.sections == ("shifts",)
    assert again.profile_visibility == "managers"
    assert again.allow_hide_media is False


# --------------------------------------------------------------------------
# Кто видит чужую активность
# --------------------------------------------------------------------------


def test_colleagues_policy_respects_personal_choice():
    viewer = _person(1)
    open_profile = _person(2, profile_public=True)
    closed_profile = _person(2, profile_public=False)
    assert hr_profile.may_view(viewer, open_profile, policy="colleagues")
    assert not hr_profile.may_view(viewer, closed_profile, policy="colleagues")


def test_managers_policy_hides_activity_from_colleagues():
    viewer = _person(1)
    target = _person(2, profile_public=True)
    assert not hr_profile.may_view(viewer, target, policy="managers")


def test_all_open_policy_beats_closed_profile():
    viewer = _person(1)
    target = _person(2, profile_public=False)
    assert hr_profile.may_view(viewer, target, policy="all_open")


def test_manager_sees_own_department_even_when_profile_is_closed():
    viewer = _person(1, role=ROLE_AUP, department_id=7)
    target = _person(2, department_id=7, profile_public=False)
    assert hr_profile.may_view(viewer, target, policy="colleagues")


def test_manager_does_not_see_foreign_department_without_watch_right():
    viewer = _person(1, role=ROLE_AUP, department_id=7)
    target = _person(2, department_id=8, profile_public=False)
    assert not hr_profile.may_view(viewer, target, policy="colleagues")
    # А если организация разрешила наблюдение между отделами — видит.
    assert hr_profile.may_view(
        viewer, target, policy="colleagues", cross_department_watch=True
    )


def test_admin_sees_anyone():
    viewer = _person(1, role=ROLE_ADMIN, department_id=None)
    target = _person(2, department_id=8, profile_public=False)
    assert hr_profile.may_view(viewer, target, policy="managers")


def test_self_always_sees_own_card():
    viewer = _person(1, profile_public=False)
    assert hr_profile.may_view(viewer, viewer, policy="managers")
