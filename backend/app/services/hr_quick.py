"""«Сказал — стало поручением» (план, 8.5).

Руководитель видит проблему в зале и не хочет идти в админку: сказал фразу —
она превращается в поручение с исполнителем и сроком. Экономится самый дорогой
шаг — вход в форму: не «открыть админку → поручения → создать → выбрать отдел →
выбрать человека → выставить дату», а «продиктовал → подтвердил».

Модуль намеренно **чистый**: ни базы, ни HTTP, ни Telegram. Строку разбирает
функция `parse`, и это единственное место, где живут правила:

* **Срок** ищется словами, которыми его называют в зале: «сегодня», «завтра»,
  «к пятнице», «до 18:00», «через два часа», «к закрытию». Если ничего не
  сказано — срок ставится на закрытие смены **сегодня** (а если смена уже
  закрылась — на завтра): «сделай когда-нибудь» в ресторане означает «до конца
  смены», а не «срок не нужен».
* **Исполнитель** ищется по составу: имя, фамилия, должность («повар»).
  Неоднозначность («две Ани») не угадывается: черновик приходит без
  исполнителя и со списком кандидатов — угадывание здесь дороже лишнего тапа,
  потому что поручение уходит чужому человеку и он получает уведомление.
* **Срочность и фотоотчёт** — тоже из слов: «срочно», «скинь фото». Это те
  решения, которые руководитель и так держит в голове, когда диктует.

Что сознательно НЕ делается:

* текст не переписывается моделью и не «улучшается» — если руководитель
  сказал «протри витрину», в поручении будет «Протри витрину», а не
  «Осуществить очистку витринного оборудования»;
* голос не уходит на сервер: расшифровка идёт в браузере (см. фронтенд), а
  сюда приходит уже текст — так нет ни оплаты за STT, ни чужого аудио в базе.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from app.db.hr_models import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    TASK_SCOPE_DEPARTMENT,
    TASK_SCOPE_EMPLOYEE,
)

# Больше 200 символов в заголовке поручения всё равно не читается в карточке,
# а «простыня» из голосовой расшифровки легко даёт 500.
MAX_TITLE = 200

# Слова, которыми фразу начинают, но которые не являются делом.
_FILLERS = (
    "надо ",
    "нужно ",
    "нужна ",
    "пусть ",
    "скажи ",
    "сказать ",
    "поручи ",
    "поручаю ",
    "задача: ",
    "задача ",
    "запомни: ",
    "пожалуйста, ",
    "плиз, ",
)

_GROUP_WORDS = (
    "всем",
    "все",
    "всей смене",
    "смене",
    "команде",
    "отделу",
    "подразделению",
    "сотрудникам",
)

# Пн–вс. Ключи — основы слов: «пятниц» ловит «пятницу», «пятнице», «пятницы».
# Узбекские и английские названия — потому что часть смены диктует по-своему,
# и руководитель не обязан помнить, какой язык выбран в приложении.
_WEEKDAYS: dict[str, int] = {
    "понедельник": 0,
    "пн": 0,
    "dushanba": 0,
    "monday": 0,
    "вторник": 1,
    "вт": 1,
    "seshanba": 1,
    "tuesday": 1,
    "сред": 2,
    "ср": 2,
    "chorshanba": 2,
    "wednesday": 2,
    "четверг": 3,
    "чт": 3,
    "payshanba": 3,
    "thursday": 3,
    "пятниц": 4,
    "пт": 4,
    "juma": 4,
    "friday": 4,
    "суббот": 5,
    "сб": 5,
    "shanba": 5,
    "saturday": 5,
    "воскресень": 6,
    "вс": 6,
    "yakshanba": 6,
    "sunday": 6,
}

_HIGH_WORDS = ("срочно", "срочн", "asap", "немедленно", "очень важно", "горит")
_LOW_WORDS = ("не срочно", "неспешно", "когда будет время", "потом", "не горит")
_PHOTO_WORDS = ("фото", "фотк", "сфотограф", "снимок", "снимк")
_REVIEW_WORDS = ("на проверку", "проверю", "с проверкой", "пришлю на проверку")

_TIME_WORDS_OPEN = ("к открытию", "до открытия", "утром", "с утра")
_TIME_WORDS_CLOSE = (
    "к закрытию",
    "до закрытия",
    "к концу смены",
    "до конца смены",
    "вечером",
)


@dataclass(frozen=True)
class QuickPerson:
    """Кандидат в исполнители — ровно то, что нужно разбору.

    Не ORM-объект: функцию разбора вызывают и тесты без базы, и ручки с
    загруженным составом. Поля — только те, по которым идёт совпадение.
    """

    id: int
    name: str
    position: str | None = None
    department_id: int | None = None


@dataclass
class QuickDraft:
    """Черновик поручения: то, что показывается в одном экране до создания."""

    title: str
    text: str
    scope: str = TASK_SCOPE_EMPLOYEE
    assignee: QuickPerson | None = None
    department_id: int | None = None
    due_at: datetime | None = None
    # Откуда взялся срок: `time` («до 18:00»), `day` («к пятнице»),
    # `hours`/`days` («через два часа»), `shift_close` (ничего не сказано).
    due_kind: str = "shift_close"
    priority: str = PRIORITY_NORMAL
    requires_photo: bool = False
    requires_review: bool = False
    # По каким частям фразы решение не принято. Фронтенд по этому списку
    # подсвечивает «кого назначить» и «когда», а не молчит.
    unclear: list[str] = field(default_factory=list)
    # Кандидаты, если имя подошло нескольким людям или по должности их много.
    candidates: list[QuickPerson] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        """Хватает ли данных, чтобы создать поручение одним тапом."""
        return not self.unclear


def _normalise(text: str) -> str:
    """Нижний регистр, `ё`→`е` и без пунктуации по краям слов."""
    lowered = text.lower().replace("ё", "е")
    return re.sub(r"[^\w\s:]+", " ", lowered, flags=re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {word for word in _normalise(text).split() if len(word) > 2}


def _word_hits(token: str, word: str) -> bool:
    """Совпадает ли слово из фразы со словом из состава.

    Падежи: «Кузнецовой» — это «Кузнецова», а «Пете» — «Пётр» (ё уже сведена к
    е). Сравниваем по началу слова, но только для длинных основ: иначе двух-
    трёхбуквенное сокращение начнёт совпадать с половиной фразы (`ср` внутри
    «сроки» — как раз так и случилось на первом прогоне).
    """
    if token == word:
        return True
    if len(word) >= 4 and len(token) >= 4:
        return token.startswith(word[:4]) and word.startswith(token[:4])
    return False


def _weekday_token(norm: str) -> tuple[str, int] | None:
    """Слово фразы, которое называет день недели (`пятнице`), и его номер."""
    for token in re.findall(r"\w+", norm):
        for key, weekday in _WEEKDAYS.items():
            if token == key or (len(key) >= 4 and token.startswith(key)):
                return token, weekday
    return None


def _weekday_from_words(norm: str) -> int | None:
    """День недели по словам фразы (`пятнице`, `пт`, `juma`)."""
    found = _weekday_token(norm)
    return None if found is None else found[1]


def _name_parts(person: QuickPerson) -> tuple[list[str], list[str]]:
    """(все слова имени, значимые) — с вычищенным префиксом тестового пула."""
    clean = person.name.replace("[BOT]", " ").strip()
    words = [w for w in _normalise(clean).split() if w]
    return words, [w for w in words if len(w) > 2]


def _match_person(text_norm: str, tokens: set[str], person: QuickPerson) -> int:
    """Насколько фраза похожа на этого человека: 0 — никак, больше — сильнее."""
    words, meaningful = _name_parts(person)
    if not meaningful:
        return 0
    full = " ".join(words)
    # Полное имя одной строкой — самое надёжное совпадение.
    if len(words) > 1 and full and full in text_norm:
        return 5
    first = meaningful[0]
    score = 0
    if any(_word_hits(token, first) for token in tokens):
        score = 3
    # Фамилия (последнее слово) тоже годится: в зале зовут и по фамилии.
    if len(meaningful) > 1 and any(
        _word_hits(token, meaningful[-1]) for token in tokens
    ):
        score = max(score, 2)
    position = _normalise(person.position or "")
    if score == 0 and position:
        # Должность без имени: «повар» — это подсказка, но не назначение.
        for word in re.findall(r"\w+", position):
            if len(word) > 3 and any(_word_hits(token, word) for token in tokens):
                return 1
    return score


def _next_weekday(today: date, weekday: int) -> date:
    """Ближайший `weekday`, считая с сегодня (сегодня — тоже вариант)."""
    delta = (weekday - today.weekday()) % 7
    return today + timedelta(days=delta)


def _clock_from_text(norm: str, *, opens_at: time, closes_at: time) -> time | None:
    """Время суток из фразы: «до 18:00», «к 9», «к закрытию»."""
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", norm)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour, minute)
        return None
    # «к 9» / «до 9» без минут: часы заведения подсказывают, утро это или вечер.
    match = re.search(r"\b(?:к|до|в)\s+(\d{1,2})\b(?!\s*:\s*\d)", norm)
    if match:
        hour = int(match.group(1))
        if 0 <= hour <= 23:
            if hour < 12 and hour < opens_at.hour:
                hour += 12
            return time(hour, 0)
    if any(word in norm for word in _TIME_WORDS_OPEN):
        return opens_at
    if any(word in norm for word in _TIME_WORDS_CLOSE):
        return closes_at
    return None


def _day_shift(norm: str, today: date) -> int | None:
    """Сдвиг дня от сегодня: «завтра» → 1, «к пятнице» → до 6. None — не сказано."""
    if "послезавтра" in norm:
        return 2
    if "завтра" in norm:
        return 1
    if "сегодня" in norm:
        return 0
    weekday = _weekday_from_words(norm)
    if weekday is not None:
        target = _next_weekday(today, weekday)
        return (target - today).days
    return None


def _due(
    norm: str,
    *,
    now: datetime,
    opens_at: time,
    closes_at: time,
) -> tuple[datetime | None, str]:
    """Срок и подсказка, откуда он взялся.

    Подсказка — код, а не фраза: текст на трёх языках собирает интерфейс, и
    сервер не должен диктовать формулировку.
    """
    hours = re.search(r"через\s+(\d+)\s*(?:час|ч)\w*", norm)
    if hours:
        return now + timedelta(hours=int(hours.group(1))), "hours"
    days = re.search(r"через\s+(\d+)\s*(?:день|дня|дней)", norm)
    if days:
        return now + timedelta(days=int(days.group(1))), "days"

    clock = _clock_from_text(norm, opens_at=opens_at, closes_at=closes_at)
    shift = _day_shift(norm, now.date())

    if clock is None and shift is None:
        # Ничего не сказано: «до конца смены», но не в прошлом.
        candidate = datetime.combine(now.date(), closes_at, tzinfo=now.tzinfo)
        while candidate <= now:
            candidate += timedelta(days=1)
        return candidate, "shift_close"

    day = now.date() + timedelta(days=shift or 0)
    when = clock or closes_at
    candidate = datetime.combine(day, when, tzinfo=now.tzinfo)
    # «до 18:00», сказанное в 19:00, значит завтрашние 18:00 — иначе срок
    # рождается уже просроченным, и сотрудник получает просрочку за минуту.
    if shift is None and candidate <= now:
        candidate += timedelta(days=1)
    kind = "time" if clock is not None else "day"
    return candidate, kind


def _title(
    text: str,
    *,
    assignee: QuickPerson | None,
    matched_span: str | None = None,
) -> str:
    """Заголовок из той же фразы: без обращения и без хвоста про срок."""
    clean = text.strip()
    # Обращение в начале: «Аня, протри витрину».
    if assignee is not None:
        words, _ = _name_parts(assignee)
        for part in (words[0] if words else "", " ".join(words)):
            if not part:
                continue
            pattern = re.compile(rf"^\s*{re.escape(part)}\s*,?\s*", re.IGNORECASE)
            if pattern.match(clean):
                clean = pattern.sub("", clean, count=1)
                break
    if matched_span:
        # Убираем хвост, из которого взялся срок, — он уже показан отдельной
        # плашкой. Иначе в карточке «до 18:00» дублируется дважды.
        clean = re.sub(
            rf"\s*{re.escape(matched_span)}\s*[.!]?\s*$", "", clean, flags=re.IGNORECASE
        )
    # «надо», «нужно», «пожалуйста» — не дело, а вежливость.
    changed = True
    while changed:
        changed = False
        lowered = clean.lower()
        for filler in _FILLERS:
            if lowered.startswith(filler):
                clean = clean[len(filler) :]
                changed = True
                break
    clean = re.sub(r"\s+", " ", clean).strip(" .,:;-—")
    # Хвост про срок мог остаться и внутри: «протри витрину сегодня».
    for tail in (
        "сегодня",
        "завтра",
        "послезавтра",
        "срочно",
        "очень срочно",
        "к открытию",
        "к закрытию",
        "к концу смены",
        "до конца смены",
    ):
        clean = re.sub(rf"[,\s]+{tail}\s*[.!]?\s*$", "", clean, flags=re.IGNORECASE)
    clean = clean.strip(" .,:;-—")
    if not clean:
        clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return ""
    titled = clean[0].upper() + clean[1:]
    if len(titled) > MAX_TITLE:
        titled = titled[: MAX_TITLE - 1].rstrip() + "…"
    return titled


def _deadline_span(norm: str) -> str | None:
    """Что именно во фразе сказало про срок (чтобы убрать это из заголовка)."""
    patterns = (
        r"через\s+\d+\s*(?:час|ч)\w*",
        r"через\s+\d+\s*(?:день|дня|дней)",
        r"(?:к|до|в)\s+\d{1,2}:\d{2}",
        r"(?:к|до|в)\s+\d{1,2}\b",
        r"послезавтра",
        r"завтра",
        r"сегодня",
        r"к открытию",
        r"до открытия",
        r"к закрытию",
        r"до закрытия",
        r"к концу смены",
        r"до конца смены",
        r"вечером",
        r"утром",
    )
    for pattern in patterns:
        match = re.search(pattern, norm)
        if match:
            return match.group(0)
    found = _weekday_token(norm)
    # Возвращаем ровно то слово, что стоит в фразе: «к пятнице» → «пятнице».
    if found is not None:
        return found[0]
    return None


def parse(
    text: str,
    *,
    now: datetime,
    opens_at: time,
    closes_at: time,
    people: list[QuickPerson],
    my_department_id: int | None,
    me_id: int | None = None,
) -> QuickDraft:
    """Разобрать фразу руководителя в черновик поручения.

    `now` обязан быть с часовым поясом: срок «к закрытию» — местное время
    заведения, а не UTC, иначе ночная смена получает срок в 02:00 по Гринвичу.
    """
    raw = (text or "").strip()
    norm = _normalise(raw)
    tokens = _tokens(raw)

    group = any(word in tokens or word in norm for word in _GROUP_WORDS)

    scored = sorted(
        ((person, _match_person(norm, tokens, person)) for person in people),
        key=lambda pair: pair[1],
        reverse=True,
    )
    best_score = scored[0][1] if scored else 0
    named = [person for person, score in scored if score >= 2 and score == best_score]
    weak = [person for person, score in scored if score == 1]

    draft = QuickDraft(
        title=_title(raw, assignee=named[0] if named else None),
        text=raw,
        department_id=my_department_id,
    )
    span = _deadline_span(norm)
    if group:
        draft.scope = TASK_SCOPE_DEPARTMENT
        draft.department_id = my_department_id
        if my_department_id is None:
            draft.unclear.append("department")
    elif len(named) == 1:
        draft.scope = TASK_SCOPE_EMPLOYEE
        draft.assignee = named[0]
    elif not named and len(weak) == 1:
        # Совпала только должность («повар, вымой полы») и такой человек в
        # составе один — назначаем: уточнять нечего, второй «повар» спросил бы
        # «а кто именно?» на ровном месте.
        draft.scope = TASK_SCOPE_EMPLOYEE
        draft.assignee = weak[0]
    else:
        draft.scope = TASK_SCOPE_EMPLOYEE
        draft.assignee = None
        # Не угадываем: двое с одинаковым именем — это два уведомления, одно из
        # которых уходит не тому человеку.
        draft.unclear.append("assignee")
        draft.candidates = (named or weak)[:5]

    draft.due_at, draft.due_kind = _due(
        norm, now=now, opens_at=opens_at, closes_at=closes_at
    )
    # Заголовок собирается последним: к этому моменту известны и исполнитель
    # (его имя-обращение убираем), и хвост про срок.
    draft.title = _title(raw, assignee=draft.assignee, matched_span=span)
    if not draft.title:
        draft.unclear.append("title")

    # «не срочно» проверяется первым: иначе отрицание попадает под «срочно»
    # и спокойное поручение уезжает как пожар.
    if any(word in norm for word in _LOW_WORDS):
        draft.priority = PRIORITY_LOW
    elif any(word in norm for word in _HIGH_WORDS):
        draft.priority = PRIORITY_HIGH
    else:
        draft.priority = PRIORITY_NORMAL

    draft.requires_photo = any(word in norm for word in _PHOTO_WORDS)
    draft.requires_review = any(word in norm for word in _REVIEW_WORDS)
    return draft
