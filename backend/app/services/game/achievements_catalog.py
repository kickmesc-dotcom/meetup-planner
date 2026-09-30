"""GHG10: КАТАЛОГ АЧИВОК — единственное место, где они описаны.

Каталог живёт В КОДЕ, а не в таблице БД: у каждой ачивки всё равно есть трекер
в коде (`achievements.py`), поэтому строка в БД была бы вторым источником правды.
Следствие (и это требование задания «перелопатить систему в один промт»): добавить
или переименовать ачивку = правка ЭТОГО файла, миграция не нужна.

`user_achievements.code` — обычная строка без FK, поэтому смена каталога безопасна.

Три вида ачивок (`kind`):

* `counter`   — накопительная: базовый тир за первую единицу (`count >= 1`) и
  отдельные юбилейные тиры 10/20/30/50/100 как самостоятельные записи.
* `threshold` — накопительная до порога: одна запись, выдаётся на `threshold`.
* `instant`   — разовая: выдаётся ровно в момент события, накопителя нет.

Ачивки с `needs_telemetry=True` описаны здесь (чтобы лист ачивок был полным), но
их трекеры появятся на своих этапах (Э7 — мем-реакции, Э11 — донаты), потому что
нужна телеметрия, которой пока нет. Они не выдаются ниоткуда, кроме явного вызова
трекера.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from app.services.game.config import ANNIVERSARY_TIERS, tier_title

# Виды ачивок (валидируются в тесте — опечатка не должна проехать молча).
KIND_COUNTER = "counter"
KIND_THRESHOLD = "threshold"
KIND_INSTANT = "instant"
KINDS = (KIND_COUNTER, KIND_THRESHOLD, KIND_INSTANT)


@dataclass(frozen=True)
class Achievement:
    """Одна ачивка. `code` — стабильный ключ (в БД и в трекерах), не переименовывать.

    Для базовых `counter`-ачивок `tiers` содержит юбилейные пороги, а сами тиры
    разворачиваются в отдельные `Achievement` с кодом `"<base>:<tier>"` (см.
    `_expand`). `base` у тира указывает на родителя — по нему считается
    «внутренний ранг» ачивки.

    Разделение «впервые vs юбилей» держим именно так: базовая запись выдаётся на
    первый случай (`count >= 1`) и берётся ОДИН раз, а каждый юбилей — отдельная
    запись каталога со своим кодом. Так «С почином» никогда не показывает
    прогресс «18/20»: 18 — это счётчик случаев, 20 — отдельная ачивка «×20».
    """

    code: str
    title: str
    description: str
    icon: str
    kind: str
    points: int = 50
    # Для counter-базы: какие юбилеи предусмотрены. Для тира — ровно один порог.
    tiers: tuple[int, ...] = ()
    tier: int | None = None
    base: str | None = None
    # Для threshold: сколько единиц нужно набрать.
    threshold: int | None = None
    # Трекер требует телеметрии, которой пока нет (см. докстринг модуля).
    needs_telemetry: bool = False
    # Ачивка не показывается в общем списке до получения (служебные/капстоун).
    secret: bool = False


# --- Ядро каталога: только базовые записи и разовые -------------------------
# Тир-версии НЕ пишутся руками — они разворачиваются из `tiers` (`_expand`),
# чтобы набор юбилеев был один на всю систему (`config.ANNIVERSARY_TIERS`).
_BASE: tuple[Achievement, ...] = (
    # --- счётчики-накопители с юбилеями (Э4.3) ---
    Achievement(
        "chin_up",
        "С почином",
        "Стать лохом дня впервые",
        "🎲",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    Achievement(
        "first_worm",
        "Первоход",
        "Стать чуханом недели впервые",
        "🐓",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    Achievement(
        "truth_seeker",
        "Искатель истины",
        "Инициировать рулетку на выбор лоха впервые",
        "🕵️",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    Achievement(
        "generation_mouthpiece",
        "Рупор поколения",
        "Стать самым активным участником чата за неделю впервые",
        "📣",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    Achievement(
        "read_only",
        "Read only",
        "Стать самым НЕактивным участником чата за неделю впервые",
        "🔇",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    # --- разовые-мгновенные (Э4.3) ---
    Achievement("self_shot", "Самострел", "Закрутить рулетку и выпасть самому", "🎯", KIND_INSTANT),
    Achievement(
        "memelog",
        "Мемолог",
        "Скинуть мем, на который отреагировали все 5 живых участников",
        "🖼️",
        KIND_INSTANT,
        needs_telemetry=True,
    ),
    Achievement(
        "forever_alone",
        "Forever alone",
        "Скинуть мем/подборку, после которой 12 часов не было ни одного сообщения",
        "🕸️",
        KIND_INSTANT,
        needs_telemetry=True,
    ),
    Achievement(
        "informant",
        "Информатор",
        "Разметить все дни своего календаря на месяц вперёд",
        "📆",
        KIND_INSTANT,
    ),
    Achievement(
        "unemployed",
        "Безработный",
        "Четыре недели подряд добавлять в календарь хотя бы одну свободную дату",
        "🛋️",
        KIND_INSTANT,
    ),
    Achievement(
        "rewrote_history",
        "Переписал историю",
        "Инициировать реролл чухана недели",
        "✍️",
        KIND_INSTANT,
    ),
    Achievement(
        "nominator",
        "Номинатор",
        "Номинированная тобой игра победила в голосовании",
        "🏆",
        KIND_INSTANT,
    ),
    Achievement(
        "cashback",
        "Кэшбэк",
        "Впервые задонатить кому-то экспу",
        "🎁",
        KIND_INSTANT,
        needs_telemetry=True,
    ),
    Achievement(
        "don_corleone",
        "Дон Корлеоне",
        "Задонатить экспу каждому живому участнику в текущем году",
        "👑",
        KIND_INSTANT,
        needs_telemetry=True,
    ),
    # --- накопители-пороги (Э4.3) ---
    Achievement(
        "opium_for_nobody",
        "Опиум для никого",
        "Три поста подряд без единой реакции в течение 12 часов",
        "💀",
        KIND_THRESHOLD,
        threshold=3,
        needs_telemetry=True,
    ),
    Achievement(
        "vciom_agent",
        "Агент ВЦИОМ-а",
        "Создать 3 опроса",
        "📊",
        KIND_THRESHOLD,
        threshold=3,
    ),
    Achievement(
        "successful_success",
        "Успешный успех",
        "Накопить 10 постов, на которые были реакции",
        "📈",
        KIND_THRESHOLD,
        threshold=10,
        needs_telemetry=True,
    ),
    Achievement(
        "nominal_nominal",
        "Номинальный номинал",
        "Номинировать 3 игры",
        "🎮",
        KIND_THRESHOLD,
        threshold=3,
    ),
    Achievement(
        "worm_tamer",
        "Укротитель паст",
        "Ответить боту или отметить его в сообщении 10 раз",
        "🪱",
        KIND_THRESHOLD,
        threshold=10,
    ),
    # --- капстоун: единственный ранг приоритетнее ранга за уровень (Э3.4) ---
    Achievement(
        "supreme_chukhan",
        "Верховный чухан",
        "Стать лохом 100 раз — высшая ступень лестницы «С почином»",
        "🏅",
        KIND_INSTANT,
        points=100,
        secret=True,
    ),
)

# Код капстоуна, который выдаётся автоматически на последнем тире «С почином».
SUPREME_CHUKHAN_CODE = "supreme_chukhan"
SUPREME_CHUKHAN_TIER_BASE = "chin_up"
SUPREME_CHUKHAN_TIER = ANNIVERSARY_TIERS[-1]


# --------------------------------------------------------------------------
# Разделы листа ачивок
# --------------------------------------------------------------------------
# Зачем разделы в каталоге, а не в отчёте бота. Лист ачивок — длинный, и без
# группировки он читается как одна стена текста (прод-фидбек 29.09). Но
# группировка — факт про НАБОР ачивок, поэтому живёт рядом с ним: если список
# группировать в `report.py`, то новая ачивка молча окажется в чужом разделе.
# Полнота проверяется тестом (`tests/test_game_surfaces.py`), а не глазами.
#
# Формат: (код раздела, заголовок, коды ачивок). Порядок разделов = порядок
# вывода, поэтому он задан здесь же.
GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "deeds",
        "🎲 Звания и рулетка",
        (
            "chin_up",
            "first_worm",
            "truth_seeker",
            "self_shot",
            "rewrote_history",
            SUPREME_CHUKHAN_CODE,
        ),
    ),
    ("chat", "📣 Активность в чате", ("generation_mouthpiece", "read_only")),
    (
        "content",
        "🎨 Контент и мемы",
        ("memelog", "forever_alone", "opium_for_nobody", "successful_success"),
    ),
    ("calendar", "📅 Календарь и явка", ("informant", "unemployed")),
    (
        "games",
        "🗳 Опросы, игры и встречи",
        ("vciom_agent", "nominator", "nominal_nominal"),
    ),
    ("social", "🤝 Бот и подарки", ("worm_tamer", "cashback", "don_corleone")),
)

GROUP_FALLBACK = ("other", "🎁 Разное")


def group_of(code: str) -> tuple[str, str]:
    """Раздел базовой ачивки. У тира — раздел его базовой ачивки.

    Неизвестный код отдаёт «Разное», а не пропадает: новая ачивка, которую
    забыли разнести по разделам, всё равно попадёт в лист (и это заметно).
    """
    base = code.split(":", 1)[0]
    for key, title, codes in GROUPS:
        if base in codes:
            return key, title
    return GROUP_FALLBACK


def _expand(base: Achievement) -> list[Achievement]:
    """Развернуть базовую ачивку с юбилеями в неё саму + тир-записи.

    Важно для читаемости: базовая запись — это ПРО ПЕРВЫЙ раз («впервые»), а
    каждая тир-запись — отдельная ачивка про юбилей. Поэтому у тира из описания
    вырезается «впервые»: иначе вышло бы противоречие «впервые — 10-й раз».
    """
    out = [base]
    narrative = base.description.replace(" впервые", "")
    for tier in base.tiers:
        out.append(
            replace(
                base,
                code=f"{base.code}:{tier}",
                title=tier_title(base.title, tier),
                description=f"{narrative} — {tier}-й раз (юбилейная ачивка)",
                tier=tier,
                base=base.code,
            )
        )
    return out


def _build() -> dict[str, Achievement]:
    catalog: dict[str, Achievement] = {}
    for base in _BASE:
        for ach in _expand(base):
            if ach.code in catalog:  # pragma: no cover - защита от дублей в каталоге
                raise ValueError(f"duplicate achievement code: {ach.code}")
            catalog[ach.code] = ach
    return catalog


CATALOG: dict[str, Achievement] = _build()
"""Все ачивки, включая юбилейные тиры (ключ — `code`)."""


def get(code: str) -> Achievement | None:
    """Ачивка по коду. Неизвестный код → None (не падаем на старых записях)."""
    return CATALOG.get(code)


def all_achievements() -> list[Achievement]:
    """Весь каталог в порядке объявления (тиры идут сразу за своим базовым)."""
    return list(CATALOG.values())


def base_achievements() -> list[Achievement]:
    """Только «корневые» ачивки — для листа достижений (без тиров)."""
    return [a for a in CATALOG.values() if a.tier is None]


def tier_codes(base: str) -> list[str]:
    """Коды юбилейных тиров базовой ачивки, по возрастанию."""
    rows = [a for a in CATALOG.values() if a.base == base and a.tier is not None]
    return [a.code for a in sorted(rows, key=lambda a: a.tier or 0)]


def tiers_reached(base: str, count: int) -> list[str]:
    """Коды тиров базовой ачивки, которые берутся при накопленном `count`.

    Чистая функция: вызывающий код передаёт счётчик (из БД/таблицы), а каталог
    решает, что именно выдать. Используется всеми counter-трекерами.
    """
    rows = [a for a in CATALOG.values() if a.base == base and a.tier is not None]
    return [a.code for a in sorted(rows, key=lambda a: a.tier or 0) if a.tier and count >= a.tier]


def catalog_size() -> int:
    """Сколько ачивок всего (для тестов/админки)."""
    return len(CATALOG)
