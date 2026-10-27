"""Поиск по знаниям заведения: стандарты и пункты чек-листов.

Зачем это отдельным сервисом, а не «ещё один список в разделе». У сотрудника
(и особенно у нового) вопрос звучит как «как закрыть смену», а не «открой мне
четвёртый пункт базы стандартов». Пока ответ надо искать по двум разделам
глазами, люди спрашивают в чате — и ответ остаётся в чате, а не в инструкции.
Один поисковый вход снимает этот шаг: спросил — увидел пункт инструкции и пункт
чек-листа, где это делается.

Почему без полнотекстового индекса и без LLM. База знаний заведения — это
десятки стандартов и сотни пунктов, а не миллионы документов. `ILIKE` по трём
колонкам здесь быстрее, чем поддержка индекса и миграции, и, что важнее,
предсказуем: человек видит, почему результат попал в выдачу (совпадение слов), а
не «модель так решила». Если база вырастет на порядок — сюда приедет
`to_tsvector`, интерфейс сервиса от этого не изменится.

Ограничения, которые надо знать:

* морфология покрыта грубо — у слов длиннее четырёх букв отбрасывается
  окончание (`смену`/`смена` → `смен`). Это не стеммер, но для русских
  «закрыть смену» / «закрытие смены» работает;
* ищутся только активные стандарты и активные чек-листы своего подразделения —
  то же правило видимости, что в разделах, иначе поиск стал бы обходом прав;
* организация подставляется сама (тенантский фильтр в `db/tenancy.py`), в
  запросах нет ни одного ручного `org_id`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import ChecklistItem, ChecklistTemplate, Employee, Standard

# Сколько слов запроса учитываем. Дальше начинается «найди всё» — это не поиск.
MAX_WORDS = 6
# Короче двух символов слово не различает ничего: «a», «я», «в».
MIN_WORD_LEN = 2
# Запрос длиннее этого — уже не вопрос, а вставленный текст.
MAX_QUERY_LEN = 120
# Сколько кандидатов тянем из базы до ранжирования.
MAX_CANDIDATES = 60
# Радиус вырезки вокруг совпадения: две строки на телефоне.
SNIPPET_RADIUS = 70

# Слова, которые есть почти в любом вопросе и ничего не различают.
_STOP_WORDS = frozenset(
    {
        "как", "что", "где", "куда", "когда", "зачем", "почему", "мне", "нам",
        "надо", "нужно", "можно", "это", "для", "при", "или", "если", "чем",
        "кто", "всё", "все", "ещё", "уже", "был", "была", "быть", "the", "how",
        "what", "where", "when", "why", "and", "for", "with",
    }
)

# Разделители — всё, что не буква и не цифра (юникод: узбекские и русские буквы
# попадают в `\w`; подчёркивание исключаем отдельно, оно не часть слова).
_SPLIT_RE = re.compile(r"[^\w]+|_", re.UNICODE)


@dataclass(frozen=True)
class Hit:
    """Один результат поиска в форме, общей для всех источников."""

    kind: str  # "standard" | "checklist"
    id: int
    title: str
    snippet: str
    subtitle: str
    score: int = field(default=0, compare=False)


def normalise_query(raw: str) -> str:
    """Запрос в том виде, в каком он пойдёт в базу: без лишних пробелов."""
    return " ".join((raw or "").split())[:MAX_QUERY_LEN]


def query_words(raw: str) -> list[str]:
    """Значимые слова запроса: нижний регистр, без стоп-слов, без повторов.

    Если после фильтра не осталось ничего (человек написал «что делать»),
    возвращаем исходные слова: пустой запрос не должен выглядеть как «ничего
    не найдено» — это разные вещи.
    """
    text = normalise_query(raw).casefold().replace("ё", "е")
    words = [w for w in _SPLIT_RE.split(text) if len(w) >= MIN_WORD_LEN]
    meaningful = [w for w in words if w not in _STOP_WORDS]
    chosen = meaningful or words
    out: list[str] = []
    for word in chosen:
        if word not in out:
            out.append(word)
        if len(out) >= MAX_WORDS:
            break
    return out


def search_stem(word: str) -> str:
    """Основа слова для `ILIKE`: у длинных слов отбрасываем окончание.

    «закрыть» → «закры», «смену» → «смен». Грубо, но без этого «смену» не
    находило бы «смена» — а именно так люди и спрашивают.
    """
    return word[:-2] if len(word) > 4 else word


def score_text(text: str, words: list[str], weight: int) -> int:
    """Сколько стоит этот текст для выдачи: по одному баллу за каждое слово.

    Ранжирование намеренно простое и объяснимое: совпадение в заголовке весит
    больше, чем в теле, а несколько слов важнее одного. Никаких «скрытых»
    коэффициентов — иначе нельзя ответить на вопрос «почему это выше».
    """
    if not text:
        return 0
    haystack = text.casefold().replace("ё", "е")
    return sum(weight for word in words if search_stem(word) in haystack)


def snippet(text: str, words: list[str], radius: int = SNIPPET_RADIUS) -> str:
    """Кусок текста вокруг первого совпадения — с многоточиями по краям.

    Возвращает начало текста, если совпадения нет (например, слово нашлось
    только в заголовке): пустая выдача смотрится как сломанный поиск.
    """
    flat = " ".join((text or "").split())
    if not flat:
        return ""
    low = flat.casefold().replace("ё", "е")
    pos = -1
    for word in words:
        found = low.find(search_stem(word))
        if found != -1 and (pos == -1 or found < pos):
            pos = found
    if pos == -1:
        return flat[: radius * 2].strip() + ("…" if len(flat) > radius * 2 else "")
    start = max(0, pos - radius)
    end = min(len(flat), pos + radius)
    # Не режем слова посередине: сдвигаем границы к ближайшим пробелам.
    if start > 0:
        space = flat.find(" ", start)
        start = space + 1 if 0 <= space < pos else start
    if end < len(flat):
        space = flat.rfind(" ", pos, end)
        end = space if space > pos else end
    piece = flat[start:end].strip()
    return ("…" if start > 0 else "") + piece + ("…" if end < len(flat) else "")


def _like_patterns(words: list[str]) -> list[str]:
    """Шаблоны для `ILIKE` — по одному на основу слова, без пустых."""
    patterns = {f"%{search_stem(word)}%" for word in words if search_stem(word)}
    return sorted(patterns)


async def search(
    session: AsyncSession,
    *,
    query: str,
    employee: Employee,
    limit: int = 12,
) -> list[Hit]:
    """Найти стандарты и пункты чек-листов по запросу сотрудника.

    Видимость — та же, что в разделах: активные стандарты своего подразделения
    (или общие), активные чек-листы своего подразделения. Никаких чужих отделов
    и выключенных инструкций в выдаче быть не может, поэтому условия
    дублируются здесь явно, а не полагаются на «раздел и так не покажет».
    """
    words = query_words(query)
    if not words:
        return []
    patterns = _like_patterns(words)
    if not patterns:
        return []
    department_id = getattr(employee, "department_id", None)

    standards = (
        await session.scalars(
            select(Standard)
            .where(
                Standard.is_active.is_(True),
                or_(
                    Standard.department_id.is_(None),
                    Standard.department_id == department_id,
                ),
                or_(
                    *[Standard.title.ilike(p) for p in patterns],
                    *[Standard.summary.ilike(p) for p in patterns],
                    *[Standard.body.ilike(p) for p in patterns],
                ),
            )
            .order_by(Standard.sort_order, Standard.title)
            .limit(MAX_CANDIDATES)
        )
    ).all()

    items = (
        await session.execute(
            select(ChecklistItem, ChecklistTemplate.title)
            .join(ChecklistTemplate, ChecklistTemplate.id == ChecklistItem.template_id)
            .where(
                ChecklistTemplate.is_active.is_(True),
                ChecklistTemplate.department_id == department_id,
                or_(
                    *[ChecklistItem.title.ilike(p) for p in patterns],
                    *[ChecklistItem.description.ilike(p) for p in patterns],
                ),
            )
            .order_by(ChecklistTemplate.sort_order, ChecklistItem.sort_order)
            .limit(MAX_CANDIDATES)
        )
    ).all()

    hits: list[Hit] = []
    for standard in standards:
        score = (
            score_text(standard.title, words, 6)
            + score_text(standard.summary, words, 3)
            + score_text(standard.body, words, 1)
        )
        hits.append(
            Hit(
                kind="standard",
                id=standard.id,
                title=standard.title,
                snippet=snippet(standard.summary or standard.body, words),
                subtitle=standard.category,
                score=score,
            )
        )
    for item, template_title in items:
        score = score_text(item.title, words, 6) + score_text(item.description, words, 2)
        hits.append(
            Hit(
                kind="checklist",
                id=item.id,
                title=item.title,
                snippet=snippet(item.description or "", words),
                subtitle=template_title,
                score=score,
            )
        )

    # Сначала то, где совпало больше слов и где совпадение в заголовке; при
    # равенстве — стабильный порядок по названию, чтобы выдача не «прыгала».
    hits.sort(key=lambda hit: (-hit.score, hit.kind, hit.title.casefold()))
    return hits[: max(1, min(limit, 30))]
