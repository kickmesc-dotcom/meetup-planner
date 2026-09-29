"""GHG10 Э13: сводка, поминовения, случайные события и контрабанда слов.

Async-БД-стенда в проекте нет (см. `test_game_memes.py`), поэтому проверяем то,
что вообще можно проверить без Postgres: чистые решения (матчинг ответов,
склонения, текст сводки, резка сообщений) и поведение функций на фейковой
сессии с подменёнными фасадами `awards`/`journal`.

Отдельно закрепляем две регрессии, которые уже случались в этом проекте:
* подсказка «за что дают опыт» показывала «+0 XP» для событий с ценой по месту;
* длинный справочник уходил в Telegram одним куском и падал на лимите 4096.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.game import contraband, events, journal, memorial, report
from app.services.game.events_catalog import PROMPTS, PROMPTS_BY_CODE
from tests.game_fakes import FakeResult, scalar_answer

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Сессия-заглушка: очереди ответов `scalar`/`execute`, коммиты.

    Поведение `scalar` намеренно повторяет настоящую сессию: на SELECT с двумя
    колонками SQLAlchemy возвращает первую колонку первой строки, а не кортеж
    (см. `tests/game_fakes.scalar_answer`). Раньше фейк отдавал кортеж — и
    боевая ошибка «'int' object is not subscriptable» в ответе на событие
    проходила все тесты.
    """

    def __init__(
        self, *, scalars: list | None = None, rows: list | None = None
    ) -> None:
        self._scalar = list(scalars or [])
        self._rows = list(rows or [])
        self.added: list = []
        self.commits = 0

    async def get(self, *_a, **_k):
        return None  # «ключа в admin_config нет» → везде дефолты

    async def scalar(self, stmt=None, *_a, **_k):
        row = self._scalar.pop(0) if self._scalar else None
        return scalar_answer(stmt, row)

    async def scalars(self, *_a, **_k):
        return _Rows(self._scalar.pop(0) if self._scalar else [])

    async def execute(self, *_a, **_k):
        # Строки для `execute(...).first()` лежат в отдельной очереди `rows`.
        row = self._rows.pop(0) if self._rows else None
        return FakeResult(row)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


# ---------------------------------------------------------------- сводка ----


def test_digest_text_groups_by_kind():
    text = journal.build_digest_text(
        [
            {"kind": journal.KIND_ACHIEVEMENT, "text": "🏆 Аня — «С почином»"},
            {"kind": journal.KIND_ACHIEVEMENT, "text": "🏆 Митян — «Мемолог»"},
            {"kind": journal.KIND_CONTRABAND, "text": "💰 Слово «нейронка»"},
        ],
        interval_hours=6,
    )
    assert "Сводка</b> за 6 ч" in text
    # Ярлык вида печатается один раз на группу, а не перед каждой строкой.
    assert text.count("🏆 <b>Ачивки</b>") == 1
    assert text.count("💰 <b>Контрабанда</b>") == 1
    assert text.index("Ачивки") < text.index("Мемолог") < text.index("Контрабанда")


def test_digest_text_empty_is_empty():
    assert journal.build_digest_text([]) == ""


def test_digest_chunks_respect_limit():
    text = "\n".join(f"строка номер {i} " + "x" * 60 for i in range(100))
    chunks = journal.chunk_digest(text, limit=500)
    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    # Ничего не потеряли: склеенные куски дают исходный текст без переводов строк.
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_chunk_text_keeps_short_text_whole():
    assert report.chunk_text("коротко") == ["коротко"]
    assert report.chunk_text("") == []


@pytest.mark.asyncio
async def test_digest_off_sends_immediately(monkeypatch):
    sent: list[str] = []

    async def _send(text, **_kw):
        sent.append(text)
        return True

    monkeypatch.setattr(journal, "send_now", _send)
    session = _FakeSession()
    ok = await journal.announce(session, kind=journal.KIND_EVENT, text="привет")
    assert ok is True
    assert sent == ["привет"]
    assert session.added == []  # ничего не копили


@pytest.mark.asyncio
async def test_digest_on_queues_instead_of_posting(monkeypatch):
    async def _enabled(_session):
        return True

    async def _send(*_a, **_k):  # pragma: no cover — не должен вызываться
        raise AssertionError("в режиме сводки сразу в чат не пишем")

    monkeypatch.setattr(journal, "get_game_digest_enabled", _enabled)
    monkeypatch.setattr(journal, "send_now", _send)
    session = _FakeSession()
    ok = await journal.announce(
        session, kind=journal.KIND_ACHIEVEMENT, text="🏆 Аня", subject_user_id=7
    )
    assert ok is True
    assert len(session.added) == 1
    entry = session.added[0]
    assert entry.kind == journal.KIND_ACHIEVEMENT
    assert entry.subject_user_id == 7
    assert entry.sent_at is None


# ----------------------------------------------------------- поминовения ----


def test_plural_forms():
    assert memorial.plural(1, "неделя", "недели", "недель") == "неделя"
    assert memorial.plural(3, "неделя", "недели", "недель") == "недели"
    assert memorial.plural(5, "неделя", "недели", "недель") == "недель"
    assert memorial.plural(11, "неделя", "недели", "недель") == "недель"
    assert memorial.plural(21, "неделя", "недели", "недель") == "неделя"


def test_memorial_text_is_the_joke_from_the_brief():
    text = memorial.memorial_text("Митян", silent_days=21)
    assert "ровно 3 недели с последнего сообщения <b>Митян</b>" in text
    assert "Мы почти привыкли." in text
    # 20 дней — это ещё не «3 недели»: недель ровно столько, сколько натикало.
    assert "2 недели" in memorial.memorial_text("Митян", silent_days=20)


def test_silence_days_never_negative():
    today = date(2026, 9, 29)
    assert memorial.silence_days(last_day=today, today=today) == 0
    assert memorial.silence_days(last_day=date(2026, 9, 8), today=today) == 21
    assert memorial.silence_days(last_day=date(2026, 10, 1), today=today) == 0


@pytest.mark.asyncio
async def test_return_closes_memorial_and_says_he_is_here(monkeypatch):
    posted: list[str] = []

    async def _send(text, **_kw):
        posted.append(text)
        return True

    monkeypatch.setattr(journal, "send_now", _send)
    entry = SimpleNamespace(resolved_at=None)
    session = _FakeSession(scalars=[entry])
    assert await memorial.note_return(session, user_id=1, at=NOW) is True
    assert entry.resolved_at == NOW
    assert posted == [memorial.MEMORIAL_RETURN_TEXT]
    assert "ОН ЗДЕСЬ" in posted[0]


@pytest.mark.asyncio
async def test_return_is_silent_without_open_memorial(monkeypatch):
    async def _send(*_a, **_k):  # pragma: no cover
        raise AssertionError("молчать")

    monkeypatch.setattr(journal, "send_now", _send)
    session = _FakeSession(scalars=[None])
    assert await memorial.note_return(session, user_id=1, at=NOW) is False
    assert session.commits == 0


# ------------------------------------------------------ случайные события ----


def test_match_answer_by_text_and_media():
    answers = [
        {"matcher": r"^да\s*[!?.…]*$", "xp": 10, "reply": "", "media": False},
        {"matcher": r".*", "xp": 50, "reply": "", "media": True},
    ]
    assert events.match_answer(answers, text="Да!", has_media=False)["xp"] == 10
    assert events.match_answer(answers, text="нет", has_media=False) is None
    # Мем засчитывается картинкой, а не первым же текстом в чате.
    assert events.match_answer(answers, text=None, has_media=True)["xp"] == 50
    assert events.match_answer(answers, text="абракадабра", has_media=False) is None


def test_bad_regex_does_not_blow_up_matching():
    answers = [{"matcher": "([", "xp": 5, "reply": ""}]
    assert events.match_answer(answers, text="что угодно", has_media=False) is None


def test_render_reply_substitutes_name_and_xp():
    rendered = events.render_reply("🏆 <b>{name}</b>: +{xp} XP", name="Аня", xp=50)
    assert rendered == "🏆 <b>Аня</b>: +50 XP"
    # Кривой шаблон из старого промпта не должен валить начисление.
    assert events.render_reply("{oops", name="Аня", xp=1) == "{oops"


def test_every_catalog_prompt_has_a_way_to_win():
    for prompt in PROMPTS:
        assert prompt.answers, prompt.code
        assert prompt.ttl_minutes > 0
        assert any(not a.media for a in prompt.answers) or prompt.code == "meme"
        assert prompt.code in PROMPTS_BY_CODE


def test_pick_prompt_skips_cooldowns():
    import random

    rng = random.Random(1)
    used = {p.code for p in PROMPTS if p.code != "self_roast"}
    assert events.pick_prompt(used_codes=used, rng=rng).code == "self_roast"
    assert events.pick_prompt(used_codes={p.code for p in PROMPTS}, rng=rng) is None


@pytest.mark.asyncio
async def test_try_answer_closes_prompt_and_pays_once(monkeypatch):
    paid: list[tuple[int, int]] = []
    posted: list[str] = []

    async def _event(_session, user_id, *, points, prompt_id=None, at=None):
        paid.append((user_id, points))

    async def _announce(_session, *, kind, text, **_kw):
        posted.append(text)
        return True

    monkeypatch.setattr(events.awards, "event", _event)
    monkeypatch.setattr(events.journal, "announce", _announce)

    prompt = SimpleNamespace(
        id=5,
        code="first_me",
        answers=[{"matcher": r"^я$", "xp": 50, "reply": "⚡️ <b>{name}</b>: +{xp} XP"}],
        closed_at=None,
        outcome=None,
        winner_user_id=None,
    )
    # Победитель достаётся из `execute(...).first()`, а не из `scalar`: именно на
    # этом падал бой (см. `_FakeSession`). Кортеж лежит в очереди `rows`.
    session = _FakeSession(scalars=[prompt], rows=[(7, "Митян")])
    assert await events.try_answer(
        session, chat_id=-100, telegram_id=123, text="я", at=NOW
    )
    assert prompt.closed_at == NOW
    assert prompt.outcome == "won"
    assert prompt.winner_user_id == 7
    assert paid == [(7, 50)]
    assert "<b>Митян</b>" in posted[0]


@pytest.mark.asyncio
async def test_try_answer_is_silent_without_open_prompt(monkeypatch):
    monkeypatch.setattr(
        events.awards, "event", lambda *a, **k: None
    )
    session = _FakeSession(scalars=[None])
    assert not await events.try_answer(
        session, chat_id=-100, telegram_id=123, text="я", at=NOW
    )
    assert session.commits == 0


# ------------------------------------------------------------ контрабанда ----


def test_word_key_and_chance_override():
    assert contraband.word_key({"word": "Нейронка"}) == "нейронка"
    assert contraband.chance_for({}, global_chance=40) == 40
    assert contraband.chance_for({"chance": 5}, global_chance=100) == 5
    # Мусор в конфиге не должен ронять срабатывание.
    assert contraband.chance_for({"chance": "ой"}, global_chance=40) == 40


def test_variants_match_any_formulation():
    entry = {
        "word": "нейронка",
        "variants": [r"нейронк\w*", r"\bии\b", r"\bai\b"],
    }
    assert contraband.matched(entry, "опять эта нейронка всё сожрала")
    assert contraband.matched(entry, "ИИ мне подсказал")
    assert contraband.matched(entry, "ну это ai какой-то")
    assert not contraband.matched(entry, "я пошёл спать")


def test_announcement_names_owner_and_author():
    entry = {
        "word": "пиздец",
        "labels": ["пизда", "пизды", "пиздец"],
        "xp": 5,
        "note": "лицензионный сбор",
    }
    text = contraband.announcement(
        entry, owner_name="Митян", author_name="Руслан", xp=5
    )
    assert "«пиздец» обнаружено" in text
    assert "пизда, пизды, пиздец" in text
    assert "сказал Руслан" in text
    assert "<b>Митян</b> получает +5 XP" in text
    assert "лицензионный сбор" in text


def test_default_registry_covers_the_brief():
    """Слова из задания на всех шестерых участников группы."""
    owners = {entry["owner"] for entry in contraband.DEFAULT_WORDS}
    words = {entry["word"] for entry in contraband.DEFAULT_WORDS}
    assert {
        "Серж-NEO",
        "Митян",
        "Сомов",
        "Никита",
        "Кравченко",
        "Русланище",
    } <= owners
    assert {"нейронка", "пиздец", "согласен"} <= words
    assert all(entry["variants"] for entry in contraband.DEFAULT_WORDS)


def test_every_default_word_has_a_stable_owner_key():
    """Регрессия: имя владельца — плохой ключ, поэтому у всех есть tg-id.

    На боевой базе лежат «Серж-NEO» и «Русланище», а в дефолтах когда-то были
    «Серж» и «Руслан»: два слова из четырёх молча не платили никому.
    """
    for entry in contraband.DEFAULT_WORDS:
        assert isinstance(entry.get("owner_tg_id"), int), entry["word"]
    ids = [entry["owner_tg_id"] for entry in contraband.DEFAULT_WORDS]
    assert len(set(ids)) == len(ids)  # один владелец на слово, без дублей


@pytest.mark.asyncio
async def test_resolve_owner_prefers_telegram_id():
    """Владельца ищем по tg-id, даже если имя в записи не совпадает с базой."""
    entry = {"word": "нейронка", "owner": "Серж", "owner_tg_id": 306733739}
    session = _FakeSession(rows=[(1, "Серж-NEO")])
    assert await contraband.resolve_owner(session, entry) == (1, "Серж-NEO")


@pytest.mark.asyncio
async def test_resolve_owner_by_name_is_tolerant():
    """Запасной путь по имени ищет «Серж» → «Серж-NEO», а не только точно."""
    tried: list[str] = []

    async def _scalar(stmt=None, *_a, **_k):
        params = list((stmt.compile().params or {}).values()) if stmt is not None else []
        pattern = next((v for v in params if isinstance(v, str)), "")
        tried.append(pattern)
        return 5 if pattern == "Серж%" else None

    session = _FakeSession()
    session.scalar = _scalar  # type: ignore[assignment]
    entry = {"word": "нейронка", "owner": "Серж", "owner_tg_id": None}
    assert await contraband.resolve_owner(session, entry) == (5, "Серж")
    # Первый заход — точное имя, оно не нашлось; второй — префикс, он сработал.
    assert tried[:2] == ["Серж", "Серж%"]


@pytest.mark.asyncio
async def test_scan_silent_when_disabled(monkeypatch):
    async def _off(_session):
        return False

    monkeypatch.setattr(contraband, "get_game_contraband_enabled", _off)
    hits = await contraband.scan(
        _FakeSession(), author_id=1, author_name="Аня", text="нейронка", at=NOW
    )
    assert hits == []


@pytest.mark.asyncio
async def test_scan_pays_owner_and_announces(monkeypatch):
    paid: list[dict] = []
    posted: list[str] = []

    async def _contraband(_session, **kwargs):
        paid.append(kwargs)
        return True

    async def _announce(_session, *, kind, text, **_kw):
        posted.append(text)
        return True

    async def _owner(_session, entry):
        return 42, entry.get("owner")

    monkeypatch.setattr(contraband.awards, "contraband", _contraband)
    monkeypatch.setattr(contraband.journal, "announce", _announce)
    monkeypatch.setattr(contraband, "resolve_owner", _owner)

    hits = await contraband.scan(
        _FakeSession(), author_id=1, author_name="Аня", text="ну это пиздец", at=NOW
    )
    assert hits == ["пиздец"]
    assert paid and paid[0]["owner_id"] == 42
    assert paid[0]["word"] == "пиздец"
    assert "<b>Митян</b>" in posted[0]


@pytest.mark.asyncio
async def test_scan_is_silent_when_daily_cap_is_used(monkeypatch):
    async def _capped(_session, **_kwargs):
        return False

    async def _announce(*_a, **_k):  # pragma: no cover
        raise AssertionError("кэп выбран — анонса быть не должно")

    monkeypatch.setattr(contraband.awards, "contraband", _capped)
    monkeypatch.setattr(contraband.journal, "announce", _announce)
    monkeypatch.setattr(contraband, "resolve_owner", lambda *a, **k: _owner(None, {}))

    async def _owner(_session, entry):
        return 42, entry.get("owner") or "Митян"

    hits = await contraband.scan(
        _FakeSession(), author_id=1, author_name="Аня", text="пизда", at=NOW
    )
    assert hits == []


@pytest.mark.asyncio
async def test_scan_skips_words_without_owner(monkeypatch):
    resolved: list[str] = []

    async def _owner(_session, entry):
        resolved.append(entry["word"])
        return None, None

    monkeypatch.setattr(contraband, "resolve_owner", _owner)
    monkeypatch.setattr(
        contraband.awards,
        "contraband",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("некому платить")),
    )
    hits = await contraband.scan(
        _FakeSession(), author_id=1, author_name="Аня", text="согласен", at=NOW
    )
    assert hits == []
    assert resolved  # слово распознали, но владельца в базе нет


# --------------------------------------------------------------- методичка ----


def test_xp_rules_text_does_not_promise_zero_xp():
    """Регрессия: у событий с ценой «по месту» в подсказке было «+0 XP»."""
    text = report.xp_rules_text()
    assert "Случайное событие в чате — по событию" in text
    assert "Кодовое слово сработало" in text
    assert "+0 XP" not in text
    assert f"1 ранг = {report.XP_PER_LEVEL} XP" in text


def test_manual_blocks_come_from_config():
    ranks = report.manual_ranks_block()
    assert any("Ручная рулетка лоха" in line for line in ranks)
    xp_lines = report.manual_xp_block()
    assert any("Сообщение в чате" in line for line in xp_lines)


@pytest.mark.asyncio
async def test_manual_is_one_telegram_message(monkeypatch):
    async def _on(_session):
        return True

    monkeypatch.setattr(report, "is_game_enabled", _on)
    text = await report.game_manual_text(_FakeSession())
    assert text is not None
    for needle in ("Опыт", "Что открывает ранг", "Ачивки", "Контрабанда", "Поминовения", "Сводка"):
        assert needle in text, needle
    assert "«нейронка»" in text  # реестр слов доехал до читателя
    assert len(text) <= report.CHAT_MESSAGE_LIMIT


@pytest.mark.asyncio
async def test_manual_is_silent_when_game_disabled(monkeypatch):
    async def _off(_session):
        return False

    monkeypatch.setattr(report, "is_game_enabled", _off)
    assert await report.game_manual_text(_FakeSession()) is None


# ------------------------------------------------------------- регрессии ----


def test_journal_kind_labels_cover_all_kinds():
    for kind in (
        journal.KIND_ACHIEVEMENT,
        journal.KIND_HOLIDAY,
        journal.KIND_EVENT,
        journal.KIND_CONTRABAND,
        journal.KIND_MEMORIAL,
    ):
        assert kind in journal.KIND_LABELS


def test_memorial_threshold_default_matches_live_setting():
    """Дефолт кода обязан совпадать с боевой настройкой (10 дней / повтор 5).

    В задании было «ровно 3 недели» (21 день), но на боевом пороге выставлены
    10/5 — если дефолт оставить прежним, то первый же сброс конфига вернул бы
    значение, от которого отказались.
    """
    from app.services import admin_config
    from app.services.game import config

    assert config.MEMORIAL_SILENCE_DAYS == 10
    assert config.MEMORIAL_REPEAT_DAYS == 5
    assert config.MEMORIAL_REPEAT_DAYS < config.MEMORIAL_SILENCE_DAYS
    # `_game_defaults()` — то, что админка подставляет, когда ключа нет в базе.
    defaults = admin_config._game_defaults()
    assert defaults["memorial_silence_days"] == config.MEMORIAL_SILENCE_DAYS
    assert defaults["memorial_repeat_days"] == config.MEMORIAL_REPEAT_DAYS


def test_digest_defaults_are_off_and_sane():
    from app.services.game import config

    assert config.DIGEST_DEFAULT_INTERVAL in config.DIGEST_INTERVALS
    assert sorted(config.DIGEST_INTERVALS) == [1, 6, 12, 24]


@pytest.mark.asyncio
async def test_digest_due_respects_interval(monkeypatch):
    async def _interval(_session):
        return 6

    monkeypatch.setattr(journal, "get_game_digest_interval_hours", _interval)

    async def _never(_session):
        return None

    monkeypatch.setattr(journal, "get_game_digest_last_flush", _never)
    assert await journal.digest_due(_FakeSession(), now=NOW) is True

    async def _recent(_session):
        return (NOW - timedelta(hours=2)).isoformat()

    monkeypatch.setattr(journal, "get_game_digest_last_flush", _recent)
    assert await journal.digest_due(_FakeSession(), now=NOW) is False

    async def _old(_session):
        return (NOW - timedelta(hours=7)).isoformat()

    monkeypatch.setattr(journal, "get_game_digest_last_flush", _old)
    assert await journal.digest_due(_FakeSession(), now=NOW) is True
