from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AvailabilityRange, User


@dataclass
class Slot:
    starts_at: datetime
    ends_at: datetime
    score: float
    available_user_ids: list[int]
    maybe_user_ids: list[int]


def _status_weight(status: int, confidence: int) -> float:
    """Per-user score contribution for a given availability bucket.
    Spec: free=+1, maybe=+0.5 (scaled by confidence), busy or unmarked = 0.
    Confidence: 1=точно да, 5=точно нет → confidence flips sign for maybe range."""
    if status == 1:  # free
        return max(0.0, 1.2 - 0.1 * (confidence - 1))  # 1..1.2 → 0.8..1.2
    if status == 2:  # maybe
        return max(0.0, 0.7 - 0.1 * (confidence - 1))  # confidence 1=0.7, 5=0.3
    return 0.0  # busy


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(hour=int(h), minute=int(m))


def _enumerate_preset_slots(
    window_start: datetime,
    window_end: datetime,
    presets: list[dict],
) -> list[tuple[datetime, datetime]]:
    """Перебираем дни window_start..window_end и в каждом дне применяем
    пресеты вида {"start":"HH:MM","end":"HH:MM"} в TZ window_start."""
    tz = window_start.tzinfo
    pres = [
        (_parse_hhmm(p["start"]), _parse_hhmm(p["end"]))
        for p in presets
        if "start" in p and "end" in p
    ]
    if not pres:
        return []
    day = window_start.date()
    end_day = window_end.date()
    out: list[tuple[datetime, datetime]] = []
    while day <= end_day:
        for ts, te in pres:
            slot_start = datetime.combine(day, ts, tzinfo=tz)
            slot_end = datetime.combine(day, te, tzinfo=tz)
            if slot_end <= window_start or slot_start >= window_end:
                continue
            out.append((slot_start, slot_end))
        day = day + timedelta(days=1)
    return out


async def find_best_slots(
    session: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    duration: timedelta | None = None,
    step: timedelta = timedelta(hours=1),
    top_n: int = 5,
    presets: list[dict] | None = None,
) -> list[Slot]:
    """
    Кандидатные слоты строятся ОДНИМ ИЗ способов:

    1. `presets` (рекомендуемое, GHG5 POLL-HOURS1): на каждый день окна
       применяем массив `[{"start":"HH:MM","end":"HH:MM"}, ...]`. Слот = пара
       (HH:MM_start, HH:MM_end) в этот день. `duration` игнорируется.
    2. Если `presets` не задан — fallback на старое скользящее окно
       `cursor += step` с фиксированной `duration`.

    Score = сумма по пользователям best-fit weight'а их range'а, который
    полностью покрывает слот. Unmarked = 0 («занят по умолчанию»).
    """
    users = list((await session.scalars(select(User))).all())
    ranges = list(
        (
            await session.scalars(
                select(AvailabilityRange).where(
                    AvailabilityRange.starts_at < window_end,
                    AvailabilityRange.ends_at > window_start,
                )
            )
        ).all()
    )

    by_user: dict[int, list[AvailabilityRange]] = {}
    for r in ranges:
        by_user.setdefault(r.user_id, []).append(r)

    # Подготавливаем список кандидатных интервалов
    if presets:
        candidates: list[tuple[datetime, datetime]] = _enumerate_preset_slots(
            window_start, window_end, presets
        )
    else:
        if duration is None:
            duration = timedelta(hours=2)
        candidates = []
        cursor = window_start
        while cursor + duration <= window_end:
            candidates.append((cursor, cursor + duration))
            cursor += step

    slots: list[Slot] = []
    for slot_start, slot_end in candidates:
        score = 0.0
        avail: list[int] = []
        maybe: list[int] = []
        for u in users:
            best_w = 0.0
            best_status = 0
            for r in by_user.get(u.id, []):
                if r.starts_at <= slot_start and r.ends_at >= slot_end:
                    w = _status_weight(r.status, r.confidence)
                    if w > best_w:
                        best_w = w
                        best_status = r.status
            score += best_w
            if best_status == 1:
                avail.append(u.id)
            elif best_status == 2:
                maybe.append(u.id)
        if score > 0:
            slots.append(
                Slot(
                    starts_at=slot_start,
                    ends_at=slot_end,
                    score=round(score, 2),
                    available_user_ids=avail,
                    maybe_user_ids=maybe,
                )
            )

    slots.sort(key=lambda s: (-s.score, s.starts_at))

    # Greedy de-overlap: keep the highest-scoring slots that don't overlap each other.
    chosen: list[Slot] = []
    for s in slots:
        if any(not (s.ends_at <= c.starts_at or s.starts_at >= c.ends_at) for c in chosen):
            continue
        chosen.append(s)
        if len(chosen) >= top_n:
            break
    return chosen
