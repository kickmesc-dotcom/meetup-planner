"""Стартовые пакеты отрасли: что именно получает новая организация.

Что проверяем и почему:

* **слова меняются вместе с отраслью.** Салон, получивший «Залы» и «Смены»,
  читает приложение про чужой бизнес — это и есть жалоба, из-за которой шаг
  появился;
* **повторное применение ничего не делает.** Мастер настройки можно пройти
  дважды; второй проход не должен ни плодить чек-листы, ни возвращать удалённое;
* **правка руководителя сильнее пакета.** Переименованный «Кабинет» не
  затирается ничем, кроме явного `force_terms`;
* **веса опыта не переезжают между клиентами.** `admin_config` общий на
  установку: салон, применённый вторым, не должен пересчитывать опыт первому.

Env выставляем ДО импорта моделей — `Settings` требует BOT_TOKEN и т.п.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.hr_models import (  # noqa: E402
    ChecklistItem,
    ChecklistTemplate,
    Department,
)
from app.db.models import AdminConfig  # noqa: E402
from app.services import app_texts, hr_kpi, org_packs  # noqa: E402


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        for table in (
            AdminConfig.__table__,
            Department.__table__,
            ChecklistTemplate.__table__,
            ChecklistItem.__table__,
        ):
            await conn.run_sync(lambda c, table=table: table.create(c))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


# --------------------------------------------------------------------------
# Каталог
# --------------------------------------------------------------------------


def test_every_industry_has_a_pack_and_unknown_falls_back() -> None:
    # У каждой известной отрасли свой набор: иначе «пакет» — это только подпись.
    for industry in ("restaurant", "salon", "autoservice", "retail"):
        pack = org_packs.get(industry)
        assert pack.checklist_items > 0, industry
        assert pack.positions, industry
    assert org_packs.get("starship").industry == "restaurant"
    assert org_packs.known("salon") is True
    assert org_packs.known("starship") is False


def test_terms_are_a_pair_of_forms() -> None:
    # «Кабинет» и «Кабинеты» — не одно слово в двух падежах, а два места
    # подстановки: метка объекта и подпись раздела.
    salon = org_packs.get("salon").terms
    assert salon["term.hall.one"] == "Кабинет"
    assert salon["term.hall.many"] == "Кабинеты"
    # Все коды пакета обязаны существовать в каталоге текстов: опечатка в коде
    # дала бы исключение на первом же применении у клиента.
    for code in salon:
        assert code in app_texts.BY_CODE


# --------------------------------------------------------------------------
# Применение
# --------------------------------------------------------------------------


async def _add_department(session, name: str = "Мастера") -> Department:
    dep = Department(name=name, slug="masters", emoji="✂️", sort_order=0)
    session.add(dep)
    await session.commit()
    return dep


async def _templates(session) -> list[ChecklistTemplate]:
    return list(await session.scalars(select(ChecklistTemplate).order_by(ChecklistTemplate.id)))


async def test_salon_gets_words_checklists_and_kpi(session) -> None:
    await _add_department(session)

    applied = await org_packs.apply(session, industry="salon")

    assert applied.industry == "salon"
    assert applied.terms_set == 6
    terms = await app_texts.overrides(session)
    assert terms["term.shift.many"] == "Приёмы"
    assert terms["term.task.one"] == "Заявка"

    templates = await _templates(session)
    assert len(templates) == 2
    titles = {t.title for t in templates}
    assert titles == {"Открытие смены", "Закрытие смены"}

    items = list(
        await session.scalars(select(ChecklistItem).order_by(ChecklistItem.sort_order))
    )
    assert items, "пакет обязан наполнить чек-лист пунктами"
    texts = " ".join(i.title for i in items)
    # Признак отрасли, а не «включить свет»: салон обязан увидеть свой инструмент.
    assert "стерилизацию" in texts
    assert "кассу" not in texts

    rules = await hr_kpi.get_rules(session)
    assert applied.kpi_updated is True
    assert rules.xp_shift_done == 6


async def test_second_apply_changes_nothing(session) -> None:
    await _add_department(session)
    await org_packs.apply(session, industry="salon")

    again = await org_packs.apply(session, industry="salon")

    assert again.terms_set == 0
    assert again.templates_created == 0
    assert again.kpi_updated is False
    assert len(await _templates(session)) == 2
    count = await session.scalar(select(func.count()).select_from(ChecklistItem))
    assert count == 9  # 5 открытие + 4 закрытие, без дублей


async def test_renamed_term_survives_until_forced(session) -> None:
    await _add_department(session)
    await org_packs.apply(session, industry="salon")
    await app_texts.save(session, {"term.hall.one": "Рабочее место"})

    await org_packs.apply(session, industry="salon")
    assert (await app_texts.overrides(session))["term.hall.one"] == "Рабочее место"

    forced = await org_packs.apply(session, industry="salon", force_terms=True)
    assert forced.terms_set == 6
    assert (await app_texts.overrides(session))["term.hall.one"] == "Кабинет"


async def test_kpi_weights_are_left_alone_when_already_set(session) -> None:
    # Второй клиент на той же установке: веса уже правили, пакет их не трогает.
    await _add_department(session)
    await hr_kpi.update_rules(session, xp_task=40)

    applied = await org_packs.apply(session, industry="autoservice")

    assert applied.kpi_updated is False
    assert (await hr_kpi.get_rules(session)).xp_task == 40


async def test_pack_creates_a_department_when_there_is_none(session) -> None:
    # Пустая организация — не «нечего применять»: без отдела сотрудник видит
    # пустой экран и не может даже выбрать, где он работает.
    applied = await org_packs.apply(session, industry="retail")

    departments = list(await session.scalars(select(Department)))
    assert [d.name for d in departments] == ["Общее"]
    assert applied.templates_created == 2
