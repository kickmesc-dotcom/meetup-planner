"""GHG10: КАТАЛОГ АЧИВОК — единственное место, где они описаны.

Каталог живёт В КОДЕ, а не в таблице БД: у каждой ачивки всё равно есть трекер
в коде (`achievements.py`), поэтому строка в БД была бы вторым источником правды.
Следствие (и это требование задания «перелопатить систему в один промт»): добавить
или переименовать ачивку = правка ЭТОГО файла, миграция не нужна.

`user_achievements.code` — обычная строка без FK, поэтому смена каталога безопасна.

Три вида ачивок (`kind`):

* `counter`   — накопительная: база за ПЕРВЫЙ случай («впервые») и отдельные
  юбилейные тиры как самостоятельные записи. Набор тиров у каждой ачивки свой
  (`tiers`): стандартные 10/20/30/50/100 плюс, при необходимости, свой порог
  (напр. ×3 у «Агента ВЦИОМ-а»).
* `threshold` — разовый ГЕТ за накопленный порог (серия/счётчик), без «первой»
  ачивки. Оставлен только там, где «первый раз» уже покрыт своим counter'ом
  (`music_streak` — см. `music_guess`) или где порог и есть суть механики.
* `instant`   — разовая: выдаётся ровно в момент события, накопителя нет.

Ачивки с `needs_telemetry=True` описаны здесь (чтобы лист ачивок был полным), но
их трекеры появятся на своих этапах (Э7 — мем-реакции, Э11 — донаты), потому что
нужна телеметрия, которой пока нет. Они не выдаются ниоткуда, кроме явного вызова
трекера.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.services.game.config import (
    ANNIVERSARY_TIERS,
    SUPREME_CHUKHAN_LOSER_TIER,
    tier_points,
    tier_title,
)

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


# Код ачивки за 100% коллекции и её особый титул (объявлены ДО `_BASE`: каталог
# ссылается на код при импорте модуля).
COMPLETIONIST_CODE = "completionist"
COMPLETIONIST_TITLE = "Идеальный червь"

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
        # GHG11: лох дня — RNG-событие, поэтому оставляем ровно «впервые» +
        # единственный юбилей ×10 (оператор: «остальные ×20/×100 — бессмысленный
        # рандом»). Капстоун «Верховный чухан» живёт отдельно (`capstone_codes`).
        tiers=(10,),
    ),
    # Недельные звания выпадают по RNG и редко — 100 таких ждать нереально.
    # Поэтому у них короткие достижимые тиры (10 недель ≈ 2.5 месяца).
    Achievement(
        "first_worm",
        "Первоход",
        "Стать чуханом недели впервые",
        "🐓",
        KIND_COUNTER,
        # GHG11: чухан — тоже RNG; «впервые» + юбилей ×10, без прочих тиров.
        tiers=(10,),
    ),
    Achievement(
        "truth_seeker",
        "Искатель истины",
        "Инициировать рулетку на выбор лоха впервые",
        "🕵️",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    # GHG11(3): магический шар. База — «впервые спросил», юбилей — ×10
    # (оператор: «за первое использование + отдельно за 10 раз»).
    Achievement(
        "advice_seeker",
        "Пифия",
        "Спросить магический шар впервые",
        "🔮",
        KIND_COUNTER,
        tiers=(10,),
    ),
    # 10% шанс, что шар пошлёт нахуй. Отдельная instant-ачивка «за то, что послали».
    Achievement(
        "advice_sent",
        "Иди на хуй",
        "Попасть под 10% шанс, когда магический шар посылает тебя куда подальше",
        "🖕",
        KIND_INSTANT,
    ),
    Achievement(
        "generation_mouthpiece",
        "Рупор поколения",
        "Стать самым активным участником чата за неделю впервые",
        "📣",
        KIND_COUNTER,
        tiers=(3, 5, 10),
    ),
    Achievement(
        "read_only",
        "Read only",
        "Стать самым НЕактивным участником чата за неделю впервые",
        "🔇",
        KIND_COUNTER,
        tiers=(3, 5, 10),
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
        "Задонатить экспу кому-то впервые",
        "🎁",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
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
    # --- накопители с юбилеями (Э4.3) ---
    # Раньше это были «пороги» (одна запись на N-й раз), но оператор потребовал
    # жёстко развести «первый раз» и «юбилей»: теперь база — «впервые», а старый
    # порог — один из юбилейных тиров (у опросов/номинаций/опиума это ×3, у
    # успешного успеха/укротителя — стандартный ×10). Порог «3» добавлен в
    # НАБОР ТИРОВ конкретной ачивки, а не в глобальный ANNIVERSARY_TIERS.
    Achievement(
        "opium_for_nobody",
        "Опиум для никого",
        "Постить в пустоту впервые (пост без реакции 12 ч)",
        "💀",
        KIND_COUNTER,
        tiers=(3, *ANNIVERSARY_TIERS),
        needs_telemetry=True,
    ),
    Achievement(
        "vciom_agent",
        "Агент ВЦИОМ-а",
        "Создать опрос впервые",
        "📊",
        KIND_COUNTER,
        tiers=(3, *ANNIVERSARY_TIERS),
    ),
    Achievement(
        "successful_success",
        "Успешный успех",
        "Опубликовать пост с реакциями впервые",
        "📈",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
        needs_telemetry=True,
    ),
    Achievement(
        "nominal_nominal",
        "Номинальный номинал",
        "Номинировать игру впервые",
        "🎮",
        KIND_COUNTER,
        tiers=(3, *ANNIVERSARY_TIERS),
    ),
    Achievement(
        "worm_tamer",
        "Укротитель паст",
        "Ответить боту или отметить его в сообщении впервые",
        "🪱",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    # --- Э14/Э15/Э16: голосовые задания, предложка и мьюзик-гейм ---
    # Задание: ачивки под новые соц-механики — голосовые, предложку и игру.
    Achievement(
        "voice_debut",
        "Голос из народа",
        "Подать голосовой вариант на задание впервые",
        "🎙️",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    Achievement(
        "voice_winner",
        "Лучший голос",
        "Победить в голосовании за лучший голосовой вариант впервые",
        "🥇",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    Achievement(
        "music_dj",
        "Диджей недели",
        "Твой трек попал в подборку впервые",
        "🎧",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    Achievement(
        "music_guess",
        "Меломан",
        "Угадать автора трека в мьюзик-гейме впервые",
        "🎵",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    Achievement(
        "music_spotlight",
        "На виду",
        "Твой трек засветился в мьюзик-гейме впервые",
        "🔦",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    # Серия — не «впервые/юбилей»: первый раз даёт `music_guess` (выше), а эта
    # ачивка — отдельный ГЕТ за серию, поэтому остаётся пороговой.
    Achievement(
        "music_streak",
        "На слуху",
        "Угадать автора трека пять раз подряд",
        "🔥",
        KIND_THRESHOLD,
        threshold=5,
    ),
    # --- капстоун: единственный ранг приоритетнее ранга за уровень (Э3.4) ---
    Achievement(
        "supreme_chukhan",
        "Верховный чухан",
        f"Стать лохом {SUPREME_CHUKHAN_LOSER_TIER} раз — высшая ступень лестницы «С почином»",
        "🏅",
        KIND_INSTANT,
        points=100,
        secret=True,
    ),
    # --- Э18: червь-господин и «идеальный червь» ---
    # Пара ачивок про режим червя-господина (T3.6): собственно звание и кара.
    Achievement(
        "worm_lord",
        "Червь-господин",
        "Стать червём-господином (повелителем бота) впервые",
        "👑",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    Achievement(
        "punisher",
        "Каратель",
        "Натравить бота на недруга через /punish впервые",
        "⚔️",
        KIND_COUNTER,
        tiers=ANNIVERSARY_TIERS,
    ),
    # --- Э19: «весёлые» ачивки про кару червя ---
    # Суточные, поэтому instant (событие уже само по себе ограничено днём).
    # Учёт ведётся по `event_log` (kind='worm_punish'): и счётчик за день, и
    # уникальные цели — без новой таблицы и миграции.
    Achievement(
        "punish_day3",
        "Тройная кара",
        "Применить кару три раза за одни сутки",
        "⚡",
        KIND_INSTANT,
    ),
    Achievement(
        "punish_all",
        "Каратель всея чата",
        "Наказать каждого участника чата, уложившись в одни сутки",
        "☠️",
        KIND_INSTANT,
    ),
    Achievement(
        "punish_bot",
        "Не по чину",
        "Попытаться наказать самого бота",
        "🤖",
        KIND_INSTANT,
    ),
    # Капстоун-коллекция: собрать ВСЕ ачивки каталога (кроме себя самой).
    # Даёт особый титул (см. `COMPLETIONIST_TITLE`) — выше «Верховного чухана».
    Achievement(
        COMPLETIONIST_CODE,
        "Идеальный червь",
        "Собрать 100% всех ачивок чата",
        "🌟",
        KIND_INSTANT,
        points=500,
        secret=True,
    ),
)

# Код капстоуна, который выдаётся автоматически на последнем тире «С почином».
SUPREME_CHUKHAN_CODE = "supreme_chukhan"
SUPREME_CHUKHAN_TIER_BASE = "chin_up"
# Порог берём из config (аудит выполнимости): не ANNIVERSARY_TIERS[-1], иначе
# капстоун «Идеального червя» ждал бы 100 RNG-выпадений лохом дня.
SUPREME_CHUKHAN_TIER = SUPREME_CHUKHAN_LOSER_TIER


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
            "advice_seeker",
            "advice_sent",
            "self_shot",
            "rewrote_history",
            SUPREME_CHUKHAN_CODE,
            COMPLETIONIST_CODE,
        ),
    ),
    (
        "worm_master",
        "🪱 Червь-господин",
        ("worm_lord", "punisher", "punish_day3", "punish_all", "punish_bot"),
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
    (
        "voice_music",
        "🎧 Голос и музыка",
        (
            "voice_debut",
            "voice_winner",
            "music_dj",
            "music_guess",
            "music_spotlight",
            "music_streak",
        ),
    ),
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
    # Срезаем «впервые» в ЛЮБОМ регистре и позиции — иначе юбилейный тир
    # противоречил бы сам себе («впервые … 10-й раз»). Именно эта путаница и
    # есть правило оператора: «впервые» и «юбилей» — две РАЗНЫЕ ачивки.
    narrative = re.sub(r"\s*впервые\s*", " ", base.description, flags=re.IGNORECASE)
    narrative = re.sub(r"\s{2,}", " ", narrative).strip()
    for tier in base.tiers:
        out.append(
            replace(
                base,
                code=f"{base.code}:{tier}",
                title=tier_title(base.title, tier),
                description=f"{narrative} — {tier}-й раз (юбилейная ачивка)",
                points=tier_points(base.points, tier),
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
