"""GHG8 P6 — генератор фраз v2 «с типажами» (без LLM).

Идея (GHG7.txt стр. 151–179): вместо нарезки чужих сообщений — заранее
прописанный типаж участника: набор шаблонов с грамм. слотами. Выбор
участника взвешен по его активности в чате (кто больше пишет — тот чаще
«вещает»), шаблон берётся из его персоналии, слоты заполняются случайными
значениями.

Тексты персоналий живут ТОЛЬКО в Neon (`participant_personas`, P6.1) —
проект публикуется открытым гитом, в репо их нельзя. Сидинг — руками
через админку (P6.1.b).

Формат persona_text (редактируется в админке, человекочитаемый):

    [шаблоны]
    Я блять ненавижу {объект}
    {мудрость}... как говорили древние
    [объект]
    индусов
    понедельники
    [мудрость]
    терпение — путь самурая

Секция `[шаблоны]` — список шаблонов (по одному на строку); любая другая
секция `[имя]` — слот: список значений (по одному на строку). Плейсхолдер
`{имя}` в шаблоне заменяется случайным значением слота. Пустые строки и
строки с `#` в начале игнорируются. Шаблон без плейсхолдеров валиден
(готовая фраза). Шаблон с плейсхолдером, для которого нет слота, на
рендере отбрасывается (см. `render_phrase`).

Нагрузка на Neon: один SELECT всех персоналий + один COUNT сообщений
в момент генерации (по расписанию/кнопке) — паттерн P5/P7, ничего
постоянного.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, ParticipantPersona, User

log = structlog.get_logger()

_SECTION_RE = re.compile(r"^\[([^\[\]]+)\]\s*$")
_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")

TEMPLATES_SECTION = "шаблоны"

# Базовый вес участника без единого сообщения в окне активности: персоналия
# есть — значит, должен иногда «вещать», даже если молчит (Никита, канонично).
BASE_ACTIVITY_WEIGHT = 1.0


@dataclass
class Persona:
    templates: list[str] = field(default_factory=list)
    slots: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        return bool(self.templates)


def parse_persona(text: str | None) -> Persona:
    """Разобрать persona_text на шаблоны и слоты. Толерантен к мусору:
    строки до первой секции игнорируются, пустые секции допустимы."""
    p = Persona()
    if not text:
        return p
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _SECTION_RE.match(line)
        if m:
            current = m.group(1).strip().lower()
            continue
        if current is None:
            continue  # текст до первой секции — преамбула, не используется
        if current == TEMPLATES_SECTION:
            p.templates.append(line)
        else:
            p.slots.setdefault(current, []).append(line)
    return p


def render_phrase(persona: Persona, rng: random.Random | None = None) -> str | None:
    """Выбрать случайный шаблон и заполнить слоты. Шаблоны, у которых есть
    плейсхолдер без значений в слотах, отбрасываются (админ увидит это
    глазами в превью — «битый» шаблон просто не выпадает). None — если
    пригодных шаблонов нет."""
    rng = rng or random.Random()
    candidates = [
        t
        for t in persona.templates
        if all(
            persona.slots.get(name.strip().lower())
            for name in _PLACEHOLDER_RE.findall(t)
        )
    ]
    if not candidates:
        return None
    template = rng.choice(candidates)

    def _fill(m: re.Match[str]) -> str:
        values = persona.slots[m.group(1).strip().lower()]
        return rng.choice(values)

    out = _PLACEHOLDER_RE.sub(_fill, template).strip()
    if out and not out.endswith((".", "!", "?", "…", ")")):
        out += "."
    return out or None


def weighted_pick_user(
    activity: dict[int, int],
    candidate_uids: list[int],
    rng: random.Random | None = None,
) -> int | None:
    """P6.2.a: выбрать участника по весу активности. Вес = BASE + число
    сообщений в окне — активные «вещают» чаще, молчуны не выпадают из
    ротации полностью."""
    if not candidate_uids:
        return None
    rng = rng or random.Random()
    weights = [BASE_ACTIVITY_WEIGHT + activity.get(uid, 0) for uid in candidate_uids]
    return rng.choices(candidate_uids, weights=weights, k=1)[0]


async def fetch_personas(session: AsyncSession) -> dict[int, str]:
    """user_id → persona_text (все строки таблицы; их максимум 6)."""
    rows = (await session.scalars(select(ParticipantPersona))).all()
    return {r.user_id: r.persona_text for r in rows}


async def fetch_activity(
    session: AsyncSession, lookback_days: int
) -> dict[int, int]:
    """user_id → число сообщений за окно. Один GROUP BY COUNT — дёшево."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows = (
        await session.execute(
            select(ChatMessage.user_id, sa_func.count())
            .where(ChatMessage.sent_at >= cutoff)
            .group_by(ChatMessage.user_id)
        )
    ).all()
    return {int(uid): int(cnt) for uid, cnt in rows}


async def compose_persona_phrase(
    session: AsyncSession,
    *,
    lookback_days: int = 7,
) -> str | None:
    """Собрать фразу v2: участник по весу активности → шаблон из его
    персоналии → заполнение слотов. Возвращает HTML-готовый текст в том же
    формате, что v1 («👤 Имя вещает»), или None, если ни одной пригодной
    персоналии нет (вызывающий код фолбэчится на legacy — функционал
    не теряется, GHG7.txt стр. 162)."""
    personas_raw = await fetch_personas(session)
    parsed = {uid: parse_persona(t) for uid, t in personas_raw.items()}
    usable = {uid: p for uid, p in parsed.items() if p.is_usable}
    if not usable:
        log.info("personas.no_usable_personas", total_rows=len(personas_raw))
        return None

    activity = await fetch_activity(session, lookback_days)
    uid = weighted_pick_user(activity, list(usable.keys()))
    assert uid is not None  # usable непуст
    phrase = render_phrase(usable[uid])
    if phrase is None:
        # Все шаблоны выбранного юзера «битые» (слоты без значений) — редко;
        # пробуем остальных по убыванию веса, чтобы пост не сорвался.
        for other_uid in sorted(
            usable, key=lambda u: activity.get(u, 0), reverse=True
        ):
            if other_uid == uid:
                continue
            phrase = render_phrase(usable[other_uid])
            if phrase is not None:
                uid = other_uid
                break
    if phrase is None:
        log.warning("personas.all_templates_broken", users=len(usable))
        return None

    user = await session.get(User, uid)
    author_name = user.display_name if user else "Кто-то из наших"
    log.info(
        "personas.composed",
        user_id=uid,
        activity=activity.get(uid, 0),
        templates=len(usable[uid].templates),
    )
    return f"👤 <b>{author_name} вещает:</b>\n\n«<i>{phrase}</i>»"
