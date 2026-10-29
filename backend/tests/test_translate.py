"""Перевод данных (план, 11): кэш, честный отказ и границы ручки.

Что здесь проверяется и почему именно это.

* **Второй раз не считаем.** Кэш — не оптимизация, а условие работы: Amvera на
  0,5 ГБ модель не поднимает и живёт только тем, что посчитал HF Space. Если
  кэш перестанет читаться, перевод просто исчезнет на боевом домене, и заметить
  это по коду нельзя.
* **Отказ виден, а не замаскирован.** Без модели сервер обязан сказать
  `available=false` и не возвращать вместо перевода пустую строку: пустота
  выглядела бы как «перевод получился, но пустой» и человек жал бы кнопку ещё
  раз.
* **Латиницу не трогаем.** «Wi-Fi», «VIP-зал», имена — не русский текст;
  перевод таких строк тратил бы запрос и портил названия.
* **Границы ручки.** 20 строк по 500 символов — это блок задания; всё, что
  больше, должно отбиваться кодом `400`, а не молча резаться.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api import routes_hr  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import TranslationCache  # noqa: E402
from app.services import translate as mt  # noqa: E402

TABLES = ("translation_cache",)


class FakeProvider:
    """Переводчик-заглушка: считает вызовы и помечает строки языком.

    Настоящая модель в тестах не нужна и вредна: 330 МБ на каждый прогон — это
    минуты ожидания, а проверяем мы не качество перевода, а то, что вокруг него
    (кэш, отказ, границы).
    """

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def available(self) -> bool:
        return True

    def supports(self, target: str) -> bool:
        return target in ("en", "uz")

    async def translate(self, texts: list[str], target: str) -> list[str]:
        self.calls.append(list(texts))
        return [f"[{target}] {text}" for text in texts]


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


def test_needs_translation_only_cyrillic() -> None:
    assert mt.needs_translation("Помыть пол в зале") is True
    # Смешанная строка переводится: русские слова в ней есть, и без перевода
    # человек поймёт из неё только «Wi-Fi». Отдельная проверка на то, что
    # латинские вкрапления не отменяют перевод.
    assert mt.needs_translation("Wi-Fi в VIP-зале") is True
    # А вот чистая латиница — это уже не русский текст: ни «Wi-Fi», ни
    # узбекское «Zalni yuvish kerak» переводить нечего.
    assert mt.needs_translation("Wi-Fi in VIP hall") is False
    assert mt.needs_translation("Zalni yuvish kerak") is False


def test_cache_key_ignores_extra_spaces_but_not_case() -> None:
    first = mt.cache_key("Помыть   пол  в зале", "uz")
    second = mt.cache_key("Помыть пол в зале", "uz")
    assert first == second
    # Регистр — часть текста: «Мойка» и «мойка» могут значить разное.
    assert mt.cache_key("Помыть пол", "uz") != mt.cache_key("помыть пол", "uz")
    # Язык входит в ключ: иначе английский перевод выдался бы за узбекский.
    assert mt.cache_key("Помыть пол", "uz") != mt.cache_key("Помыть пол", "en")


@pytest.mark.asyncio
async def test_second_request_comes_from_cache(session) -> None:
    provider = FakeProvider()
    items, reason = await mt.translate_texts(
        session, ["Помыть пол в зале"], "uz", provider=provider
    )
    assert reason is None
    assert items[0].translated == "[uz] Помыть пол в зале"
    assert len(provider.calls) == 1

    items2, reason2 = await mt.translate_texts(
        session, ["Помыть пол в зале"], "uz", provider=provider
    )
    assert reason2 is None
    assert items2[0].translated == items[0].translated
    # Модель больше не звали — иначе кэш был бы бесполезен на Amvera.
    assert len(provider.calls) == 1

    count = await session.scalar(select(func.count()).select_from(TranslationCache))
    assert count == 1


@pytest.mark.asyncio
async def test_duplicates_within_request_are_translated_once(session) -> None:
    provider = FakeProvider()
    items, _ = await mt.translate_texts(
        session,
        ["Проверить кассу", "Проверить кассу", "Wi-Fi in hall"],
        "en",
        provider=provider,
    )
    assert [item.translated for item in items] == [
        "[en] Проверить кассу",
        "[en] Проверить кассу",
        None,
    ]
    # Латиница в модель не уходит вовсе.
    assert provider.calls == [["Проверить кассу"]]
    assert items[2].provider == mt.PROVIDER_CACHE_SAME


@pytest.mark.asyncio
async def test_without_model_it_says_so_instead_of_faking(session) -> None:
    items, reason = await mt.translate_texts(
        session, ["Закрыть смену и сдать кассу"], "uz", provider=None
    )
    assert reason == "model_unavailable"
    assert items[0].translated is None
    assert items[0].provider is None


@pytest.mark.asyncio
async def test_without_model_cache_still_works(session) -> None:
    provider = FakeProvider()
    await mt.translate_texts(session, ["Открыть зал"], "uz", provider=provider)

    # Второй контейнер: модели нет, но посчитанное уже лежит в общей базе.
    items, reason = await mt.translate_texts(
        session, ["Открыть зал"], "uz", provider=None
    )
    assert reason is None
    assert items[0].translated == "[uz] Открыть зал"


@pytest.mark.asyncio
async def test_partial_cache_reports_only_missing(session) -> None:
    provider = FakeProvider()
    await mt.translate_texts(session, ["Первый пункт"], "uz", provider=provider)

    items, reason = await mt.translate_texts(
        session, ["Первый пункт", "Второй пункт"], "uz", provider=None
    )
    # Первое отдаём из кэша, второе — нет, и об этом сказано честно.
    assert items[0].translated == "[uz] Первый пункт"
    assert items[1].translated is None
    assert reason == "model_unavailable"


@pytest.mark.asyncio
async def test_route_rejects_oversized_requests(session) -> None:
    with pytest.raises(HTTPException) as empty:
        await routes_hr.translate_data(
            routes_hr.TranslateIn(target="uz", texts=[]), session, None
        )
    assert empty.value.detail == "empty_texts"

    too_many = routes_hr.TranslateIn(
        target="uz", texts=["Пункт"] * (mt.MAX_TEXTS + 1)
    )
    with pytest.raises(HTTPException) as many:
        await routes_hr.translate_data(too_many, session, None)
    assert many.value.detail == "too_many_texts"

    long_text = routes_hr.TranslateIn(
        target="uz", texts=["я" * (mt.MAX_TEXT_CHARS + 1)]
    )
    with pytest.raises(HTTPException) as long_exc:
        await routes_hr.translate_data(long_text, session, None)
    assert long_exc.value.detail == "text_too_long"


@pytest.mark.asyncio
async def test_route_answers_in_request_order(session, monkeypatch) -> None:
    provider = FakeProvider()

    # Ручка берёт провайдера из окружения — подменяем фабрику, а не модель.
    monkeypatch.setattr(mt, "get_provider", lambda: provider)

    body = routes_hr.TranslateIn(
        target="en",
        texts=["Помыть пол", "Wi-Fi area", "Помыть пол"],
    )
    out = await routes_hr.translate_data(body, session, None)

    assert out.available is True
    assert out.target == "en"
    assert [item.translated for item in out.items] == [
        "[en] Помыть пол",
        None,
        "[en] Помыть пол",
    ]


@pytest.mark.asyncio
async def test_route_without_model_is_honest(session, monkeypatch) -> None:
    monkeypatch.setattr(mt, "get_provider", lambda: None)
    out = await routes_hr.translate_data(
        routes_hr.TranslateIn(target="uz", texts=["Закрыть смену"]), session, None
    )
    assert out.available is False
    assert out.reason == "model_unavailable"
    assert out.items[0].translated is None


def test_route_is_mounted_where_the_client_calls_it() -> None:
    """Путь в клиенте и путь на сервере — одно и то же.

    Зачем отдельная проверка. Первая выкладка положила ручку на
    `/api/translate` (роутер HR монтируется с `prefix="/api"`), а фронтенд звал
    `/api/hr/translate` — живой хост ответил 404, и кнопка молча не работала.
    Ни один из тестов сервиса этого поймать не мог: они вызывают функцию
    напрямую, без маршрутизации.
    """
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/hr/translate" in paths
