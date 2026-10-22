"""Раунд 5: расписание по дням недели, видимость профиля, история изменений.

Проверяем чистые правила — те, на которых держится поведение:

* пункт «по четвергам» действует только в четверг, но виден всегда;
* прогресс чек-листа считает только сегодняшние пункты;
* коллега видит карточку только у открытого профиля, руководитель — всегда;
* `/changelog` не показывает технический текст коммита.
"""

from __future__ import annotations

import os
from datetime import date, datetime

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from app.db.hr_models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    ChecklistItem,
    Employee,
)
from app.services import changelog, hr_checklists, hr_profile, weekdays  # noqa: E402

MONDAY = date(2026, 10, 19)
THURSDAY = date(2026, 10, 22)
FRIDAY = date(2026, 10, 23)


# --------------------------------------------------------------------------
# Расписание по дням недели
# --------------------------------------------------------------------------


def test_parse_accepts_csv_and_ignores_garbage():
    assert weekdays.parse("1,4") == (1, 4)
    assert weekdays.parse("4, 1,4") == (1, 4)
    assert weekdays.parse("0,9,ч") == ()
    assert weekdays.parse(None) == ()
    assert weekdays.parse("") == ()


def test_dump_is_none_for_every_day():
    """Пустой список — это «каждый день», а не пустая строка в базе."""
    assert weekdays.dump([]) is None
    assert weekdays.dump([4]) == "4"
    assert weekdays.dump([5, 1, 1]) == "1,5"


def test_thursday_only_item_is_active_only_on_thursday():
    assert weekdays.is_active_on("4", THURSDAY)
    assert not weekdays.is_active_on("4", MONDAY)
    # Без расписания пункт действует каждый день.
    assert weekdays.is_active_on(None, MONDAY)


def test_human_labels_read_like_speech():
    assert weekdays.label("4") == "по четвергам"
    assert weekdays.label("1,2,3,4,5") == "по будням"
    assert weekdays.label("6,7") == "по выходным"
    assert weekdays.label("1,3,5") == "Пн, Ср, Пт"
    assert weekdays.label(None) == ""


def test_next_active_skips_to_the_right_day():
    assert weekdays.next_active("4", THURSDAY) is None
    assert weekdays.next_active("4", MONDAY) == THURSDAY
    # Воскресенье → ближайший понедельник из набора.
    assert weekdays.next_active("1", date(2026, 10, 25)) == date(2026, 10, 26)


def _item(item_id: int, weekdays_value: str | None) -> ChecklistItem:
    return ChecklistItem(
        id=item_id,
        template_id=1,
        title=f"пункт {item_id}",
        weekdays=weekdays_value,
    )


def test_progress_counts_only_todays_items():
    items = [_item(1, None), _item(2, "4")]
    active = hr_checklists.active_items(items, MONDAY)
    assert [item.id for item in active] == [1]
    # В четверг оба пункта в счёте.
    assert len(hr_checklists.active_items(items, THURSDAY)) == 2
    # Закрытый в четверг пункт не «висит» в понедельничном прогрессе.
    assert hr_checklists.progress(active, {1, 2}).total == 1


# --------------------------------------------------------------------------
# Видимость профиля
# --------------------------------------------------------------------------


def _person(
    employee_id: int,
    *,
    role: str = ROLE_EMPLOYEE,
    department_id: int | None = None,
    public: bool = True,
) -> Employee:
    return Employee(
        id=employee_id,
        user_id=employee_id,
        role=role,
        department_id=department_id,
        profile_public=public,
    )


def test_own_profile_is_always_visible():
    me = _person(1, public=False)
    assert hr_profile.may_view(me, me)


def test_colleague_sees_only_open_profile():
    viewer = _person(1)
    open_profile = _person(2, public=True)
    closed_profile = _person(3, public=False)
    assert hr_profile.may_view(viewer, open_profile)
    assert not hr_profile.may_view(viewer, closed_profile)


def test_manager_sees_own_department_even_if_closed():
    manager = _person(1, role=ROLE_AUP, department_id=7)
    closed = _person(2, department_id=7, public=False)
    foreign = _person(3, department_id=8, public=False)
    assert hr_profile.may_view(manager, closed)
    # Чужое подразделение — только если человек сам открыл профиль.
    assert not hr_profile.may_view(manager, foreign)


def test_admin_sees_any_closed_profile():
    admin = _person(1, role=ROLE_ADMIN)
    closed = _person(2, department_id=8, public=False)
    assert hr_profile.may_view(admin, closed)


# --------------------------------------------------------------------------
# /changelog: человекочитаемая адаптация
# --------------------------------------------------------------------------


def test_technical_commit_text_never_leaks():
    text = changelog.adapt_message(
        "fix(ui): поправить `ChecklistScreen.tsx` и API-вызов"
    )
    assert text is not None
    assert "fix(" not in text
    assert "`" not in text
    assert ".tsx" not in text
    assert "API" not in text
    assert text.startswith("В интерфейсе:")


def test_internal_commits_are_skipped():
    assert changelog.adapt_message("docs(deploy): зафиксировать выкладку") is None
    assert changelog.adapt_message("chore: bump deps") is None
    assert changelog.adapt_message("test: покрыть ленту") is None


def test_commit_without_prefix_still_becomes_readable():
    text = changelog.adapt_message("Обновить README")
    assert text == "Обновить README"


def _commit(sha: str, message: str) -> changelog.Commit:
    return changelog.Commit(
        sha=sha,
        at=datetime(2026, 10, 22, 10, 0),
        raw=message,
        url=f"https://github.com/x/y/commit/{sha}",
    )


def test_changelog_uses_editorial_entries_and_skips_covered_commits():
    covered = changelog.editorial.ENTRIES[0].commits[0]
    view = changelog.build_view(
        [
            _commit(covered, "fix(ui): уже описано человеческим языком"),
            _commit("deadbee", "feat(shifts): новые смены"),
        ],
        source_ok=True,
    )
    titles = [entry.title for entry in view.entries]
    assert changelog.editorial.ENTRIES[0].title in titles
    # Покрытый редактором коммит второй раз не появляется.
    assert "уже описано человеческим языком" not in " ".join(titles)
    # Новый — появляется, и он помечен как автоматический.
    assert any(entry.automatic for entry in view.entries)


def test_render_never_dumps_raw_commit_and_mentions_github():
    view = changelog.Changelog(
        entries=[changelog.EntryView(day=THURSDAY, title="Проверка", body="Как это работает.")],
        internal_count=2,
        repo_url="https://github.com/x/y/commits/main",
        source_ok=False,
    )
    text = changelog.render_changelog(view)
    assert "Проверка" in text
    assert "внутренние улучшения" in text
    assert "github.com" in text
    # GitHub недоступен — об этом сказано честно, а не пустым экраном.
    assert "недоступен" in text


def test_changelog_render_is_html_escaped():
    view = changelog.Changelog(
        entries=[
            changelog.EntryView(day=FRIDAY, title="<script>alert(1)</script>", body="")
        ],
        source_ok=True,
    )
    text = changelog.render_changelog(view)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
