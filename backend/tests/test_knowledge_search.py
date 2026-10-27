"""Поиск по знаниям: стандарты и пункты чек-листов.

Проверяем то, от чего зависит доверие к поиску: он не должен находить чужие
подразделения и выключенные инструкции, не должен выдавать пустоту на
нормальный русский вопрос («как закрыть смену») и должен объяснимо
ранжировать — заголовок важнее тела.

Env выставляем до импорта моделей приложения: `Settings` требует BOT_TOKEN и т.п.
"""

from __future__ import annotations

import itertools
import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db import models as _models  # noqa: E402,F401 — регистрирует таблицу `users`
from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ChecklistItem,
    ChecklistTemplate,
    Department,
    Employee,
    Standard,
)
from app.services import knowledge  # noqa: E402

_STANDARD_IDS = itertools.count(1)

TABLES = [
    # `organizations`/`users` нужны не для проверок, а для FK: без них SQLAlchemy
    # не соберёт метаданные для `employees.user_id`.
    "organizations",
    "users",
    "departments",
    "standards",
    # `standard_questions` сюда не входит: у неё JSONB-колонка, которую sqlite
    # не умеет создавать, а поиску вопросы не нужны.
    "checklist_templates",
    "checklist_items",
    "employees",
]


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [Base.metadata.tables[name] for name in TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _employee(session, department_id: int | None = None) -> Employee:
    employee = Employee(user_id=1, department_id=department_id)
    session.add(employee)
    await session.flush()
    return employee


async def _standard(session, *, title: str, body: str, department_id=None, **extra):
    # У `standards.id` нет sqlite-варианта (на проде BIGSERIAL), поэтому в тесте
    # id задаётся явно — иначе NOT NULL constraint failed.
    standard = Standard(
        id=next(_STANDARD_IDS),
        title=title,
        body=body,
        category=extra.pop("category", "other"),
        department_id=department_id,
        **extra,
    )
    session.add(standard)
    await session.flush()
    return standard


# --------------------------------------------------------------------------
# Слова и вырезки — чистая логика, без базы
# --------------------------------------------------------------------------


def test_stop_words_do_not_make_the_query_empty():
    # Если в запросе одни служебные слова, вернуть надо что-то, иначе человек
    # увидит «ничего не найдено» на осмысленный вопрос «как? где?».
    assert knowledge.query_words("как что где") == ["как", "что", "где"]
    # А в нормальном вопросе служебные слова отбрасываются: остаются значимые.
    assert knowledge.query_words("как закрыть смену?") == ["закрыть", "смену"]
    assert knowledge.query_words("что делать") == ["делать"]


def test_words_are_deduplicated_and_capped():
    words = knowledge.query_words("смена смена СМЕНА открытие закрытие приёмка отчёт")
    assert words.count("смена") == 1
    assert len(words) <= knowledge.MAX_WORDS


def test_yo_is_treated_as_e():
    # Пишут и «приёмка», и «приемка» — это одно и то же слово для поиска.
    assert knowledge.query_words("приёмка") == knowledge.query_words("приемка")


def test_stem_matches_russian_endings():
    # «смену» должно находить «смена», а «закрыть» — «закрытие».
    assert knowledge.search_stem("смену") in "смена"
    assert knowledge.search_stem("закрыть") in "закрытие закрывать"


def test_snippet_is_cut_around_the_match():
    text = "длинное вступление " * 20 + "проверьте сроки годности " + "и хвост " * 20
    out = knowledge.snippet(text, ["сроки"])
    assert "сроки годности" in out
    assert out.startswith("…") and out.endswith("…")
    assert len(out) < len(text)


def test_snippet_without_match_returns_head():
    assert knowledge.snippet("короткий текст", ["нет-такого"]).startswith("короткий")


def test_title_match_scores_higher_than_body():
    words = ["смена"]
    assert knowledge.score_text("Смена", words, 6) > knowledge.score_text(
        "закрытие смены", words, 1
    )


# --------------------------------------------------------------------------
# Выдача из базы
# --------------------------------------------------------------------------


async def test_finds_standard_by_body_word(session):
    employee = await _employee(session)
    standard = await _standard(
        session,
        title="Закрытие смены",
        body="Проверьте кассы и сдайте выручку старшему менеджеру.",
    )
    hits = await knowledge.search(session, query="кассу", employee=employee)
    assert [hit.id for hit in hits] == [standard.id]
    assert hits[0].kind == "standard"
    assert "касс" in hits[0].snippet.lower()


async def test_finds_checklist_item_with_template_name(session):
    department = Department(name="Зал", slug="hall-1")
    session.add(department)
    await session.flush()
    template = ChecklistTemplate(department_id=department.id, title="Открытие зала")
    session.add(template)
    await session.flush()
    item = ChecklistItem(
        template_id=template.id,
        title="Протереть столы",
        description="Каждый стол — чистой салфеткой, не тряпкой с пола.",
    )
    session.add(item)
    await session.flush()
    employee = await _employee(session, department.id)

    hits = await knowledge.search(session, query="протереть столы", employee=employee)
    assert [hit.kind for hit in hits] == ["checklist"]
    assert hits[0].subtitle == "Открытие зала"
    assert hits[0].id == item.id


async def test_hidden_and_foreign_materials_are_not_found(session):
    own = Department(name="Зал", slug="own")
    other = Department(name="Кухня", slug="other")
    session.add_all([own, other])
    await session.flush()

    await _standard(session, title="Наш стандарт про смену", body="текст")
    await _standard(
        session, title="Смена другого отдела", body="текст", department_id=other.id
    )
    await _standard(session, title="Выключенная смена", body="текст", is_active=False)

    foreign_template = ChecklistTemplate(department_id=other.id, title="Чужое открытие")
    session.add(foreign_template)
    await session.flush()
    session.add(
        ChecklistItem(template_id=foreign_template.id, title="Смена: чужие дела")
    )
    await session.flush()

    employee = await _employee(session, own.id)
    hits = await knowledge.search(session, query="смена", employee=employee)
    titles = {hit.title for hit in hits}
    assert "Наш стандарт про смену" in titles
    assert "Смена другого отдела" not in titles
    assert "Выключенная смена" not in titles
    assert "Смена: чужие дела" not in titles


async def test_inactive_template_hides_its_items(session):
    department = Department(name="Бар", slug="bar")
    session.add(department)
    await session.flush()
    template = ChecklistTemplate(
        department_id=department.id, title="Старый чек-лист", is_active=False
    )
    session.add(template)
    await session.flush()
    session.add(ChecklistItem(template_id=template.id, title="Проверить лёд"))
    await session.flush()

    employee = await _employee(session, department.id)
    assert await knowledge.search(session, query="лёд", employee=employee) == []


async def test_title_hits_rank_above_body_hits(session):
    employee = await _employee(session)
    in_body = await _standard(
        session, title="Уборка", body="после закрытия проверьте вытяжку и сдайте смену"
    )
    in_title = await _standard(session, title="Сдача смены", body="кратко")
    hits = await knowledge.search(session, query="смена", employee=employee)
    assert [hit.id for hit in hits][:2] == [in_title.id, in_body.id]


async def test_empty_query_returns_nothing(session):
    employee = await _employee(session)
    await _standard(session, title="Что-нибудь", body="текст")
    assert await knowledge.search(session, query="   ", employee=employee) == []


async def test_limit_is_respected(session):
    employee = await _employee(session)
    # Заголовки в нижнем регистре намеренно: `LIKE` в sqlite регистронезависим
    # только для латиницы, а на проде PostgreSQL `ILIKE` — для юникода тоже.
    # Этот тест про лимит, а не про регистр, — пусть он и не зависит от движка.
    for index in range(5):
        await _standard(session, title=f"смена {index}", body="текст")
    hits = await knowledge.search(session, query="смена", employee=employee, limit=2)
    assert len(hits) == 2
