"""GHG8 T3.1: снапшот/экспорт базы причин-реакций (страховка от потери).

Пользователь надобавил через админку +100 кастомных причин/реакций для каждого
режима, не сохранив их в код/git (11.1). При следующем апдейте/пересборке БД они
могут потеряться. Этот модуль собирает ВСЕ редактируемые пулы фраз в один
JSON-снапшот, который можно скопировать/скачать, а позже залить обратно
(replace или merge).

Что входит в снапшот:
- пулы фраз: loser_reasons, chukhan_reasons, advice, media single/collection,
  media emoji-whitelist (все — admin_config, key→JSON-список);
- счётчики использования (use_counts) лоха/чухана — ключ по хэшу фразы, поэтому
  переносимы как есть (см. phrase_weights.phrase_hash);
- персонажи (типажи) — таблица participant_personas; в снапшоте КЛЮЧУЕМ по
  telegram_id (не по внутреннему user_id), чтобы снапшот пережил пересборку БД.

Чистые функции (validate_snapshot / merge_pool) вынесены без БД-IO — их и
тестируем. `build_snapshot` / `apply_snapshot` ходят в БД и тестируются вручную
(async-БД-стенда в проекте нет).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SNAPSHOT_FORMAT = "meetup-planner.phrase-snapshot"
SNAPSHOT_VERSION = 1

# Пулы фраз в admin_config: ключ снапшота → (getter, setter). Заполняется лениво
# внутри функций (избегаем импортных циклов на уровне модуля).
_POOL_KEYS = (
    "loser_reasons",
    "chukhan_reasons",
    "advice",
    "media_single",
    "media_collection",
    "media_emoji",
)

_USE_COUNT_KEYS = ("loser_reasons", "chukhan_reasons")


def merge_pool(current: list[str], incoming: list[str]) -> list[str]:
    """Слить два списка фраз: сохранить порядок current, дописать новые из
    incoming, без дублей (точное совпадение после strip)."""
    out: list[str] = []
    seen: set[str] = set()
    for src in (current, incoming):
        for raw in src:
            p = (raw or "").strip()
            if not p or p in seen:
                continue
            seen.add(p)
            out.append(p)
    return out


def validate_snapshot(data: Any) -> tuple[bool, str]:
    """Проверить структуру снапшота. Возвращает (ok, error_message).

    Мягкая валидация: требуем правильный формат-маркер и тип контейнеров.
    Отсутствующие секции допустимы (импорт применит только то, что есть)."""
    if not isinstance(data, dict):
        return False, "снапшот должен быть JSON-объектом"
    if data.get("format") != SNAPSHOT_FORMAT:
        return False, f"не тот формат (ожидается {SNAPSHOT_FORMAT})"
    ver = data.get("version")
    if not isinstance(ver, int) or ver < 1:
        return False, "отсутствует/некорректная version"
    pools = data.get("pools")
    if pools is not None:
        if not isinstance(pools, dict):
            return False, "pools должен быть объектом"
        for k, v in pools.items():
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                return False, f"pools.{k} должен быть списком строк"
    counts = data.get("use_counts")
    if counts is not None and not isinstance(counts, dict):
        return False, "use_counts должен быть объектом"
    personas = data.get("personas")
    if personas is not None:
        if not isinstance(personas, list):
            return False, "personas должен быть списком"
        for i, p in enumerate(personas):
            if not isinstance(p, dict) or "telegram_id" not in p or "persona_text" not in p:
                return False, f"personas[{i}] должен иметь telegram_id и persona_text"
    return True, ""


async def _pool_getter(session: AsyncSession, name: str) -> list[str]:
    from app.services import admin_config as ac
    from app.services import media_reactions as mr

    if name == "loser_reasons":
        return await ac.get_loser_reasons(session)
    if name == "chukhan_reasons":
        return await ac.get_chukhan_reasons(session)
    if name == "advice":
        return await ac.get_advice_phrases(session)
    if name == "media_single":
        return await mr.get_single_phrases(session)
    if name == "media_collection":
        return await mr.get_collection_phrases(session)
    if name == "media_emoji":
        return await mr.get_emoji_whitelist(session)
    raise KeyError(name)


async def _pool_setter(session: AsyncSession, name: str, phrases: list[str]) -> None:
    from app.services import admin_config as ac
    from app.services import media_reactions as mr

    if name == "loser_reasons":
        await ac.set_loser_reasons(session, phrases)
    elif name == "chukhan_reasons":
        await ac.set_chukhan_reasons(session, phrases)
    elif name == "advice":
        await ac.set_advice_phrases(session, phrases)
    elif name == "media_single":
        await mr.set_single_phrases(session, phrases)
    elif name == "media_collection":
        await mr.set_collection_phrases(session, phrases)
    elif name == "media_emoji":
        await mr.set_emoji_whitelist(session, phrases)
    else:
        raise KeyError(name)


async def build_snapshot(session: AsyncSession) -> dict[str, Any]:
    """Собрать полный снапшот всех редактируемых пулов + use_counts + персонажей."""
    from app.db.models import ParticipantPersona, User
    from app.services.phrase_weights import (
        CHUKHAN_USE_COUNTS_KEY,
        LOSER_USE_COUNTS_KEY,
        get_use_counts,
    )

    pools: dict[str, list[str]] = {}
    for name in _POOL_KEYS:
        pools[name] = await _pool_getter(session, name)

    use_counts = {
        "loser_reasons": await get_use_counts(session, LOSER_USE_COUNTS_KEY),
        "chukhan_reasons": await get_use_counts(session, CHUKHAN_USE_COUNTS_KEY),
    }

    # Персонажи: ключуем по telegram_id (стабилен между пересборками БД).
    users_by_id = {
        u.id: u for u in (await session.scalars(select(User))).all()
    }
    personas: list[dict[str, Any]] = []
    for row in (await session.scalars(select(ParticipantPersona))).all():
        u = users_by_id.get(row.user_id)
        if u is None:
            continue
        personas.append(
            {
                "telegram_id": u.telegram_id,
                "display_name": u.display_name,
                "persona_text": row.persona_text,
            }
        )

    return {
        "format": SNAPSHOT_FORMAT,
        "version": SNAPSHOT_VERSION,
        "pools": pools,
        "use_counts": use_counts,
        "personas": personas,
    }


async def apply_snapshot(
    session: AsyncSession, data: dict[str, Any], *, mode: str
) -> dict[str, Any]:
    """Применить снапшот. mode = 'replace' (перезаписать) | 'merge' (дописать
    без дублей). Возвращает summary: по каждому пулу итоговый размер +
    счётчик восстановленных персонажей/пропущенных.

    use_counts применяются только в режиме replace и только для пулов, которые
    в снапшоте присутствуют (merge их не трогает — иначе веса разъедутся с
    реально слитым списком)."""
    if mode not in ("replace", "merge"):
        raise ValueError(f"unknown mode {mode!r}")

    summary: dict[str, Any] = {"mode": mode, "pools": {}, "personas": {}}

    pools = data.get("pools") or {}
    for name in _POOL_KEYS:
        incoming = pools.get(name)
        if incoming is None:
            continue
        if mode == "merge":
            current = await _pool_getter(session, name)
            final = merge_pool(current, incoming)
        else:
            final = [p.strip() for p in incoming if p and p.strip()]
        await _pool_setter(session, name, final)
        summary["pools"][name] = {"count": len(final)}

    # use_counts — только replace (см. докстринг).
    if mode == "replace":
        from app.services.phrase_weights import (
            CHUKHAN_USE_COUNTS_KEY,
            LOSER_USE_COUNTS_KEY,
            set_use_counts,
        )

        uc = data.get("use_counts") or {}
        key_map = {
            "loser_reasons": LOSER_USE_COUNTS_KEY,
            "chukhan_reasons": CHUKHAN_USE_COUNTS_KEY,
        }
        for name, key in key_map.items():
            counts = uc.get(name)
            if isinstance(counts, dict):
                clean = {
                    str(k): int(v)
                    for k, v in counts.items()
                    if isinstance(v, int) or (isinstance(v, str) and v.lstrip("-").isdigit())
                }
                await set_use_counts(session, key, clean)

    # Персонажи: matched по telegram_id → внутренний user_id. Несуществующих
    # юзеров пропускаем (в summary — skipped). merge/replace для персонажей
    # ведут себя одинаково: текст персонажа цельный, его перезаписываем.
    personas = data.get("personas")
    if isinstance(personas, list):
        from app.db.models import ParticipantPersona, User

        users_by_tg = {
            u.telegram_id: u for u in (await session.scalars(select(User))).all()
        }
        restored = 0
        skipped = 0
        for p in personas:
            tg = p.get("telegram_id")
            text = (p.get("persona_text") or "").strip()
            u = users_by_tg.get(tg)
            if u is None or not text:
                skipped += 1
                continue
            row = await session.get(ParticipantPersona, u.id)
            if row is None:
                session.add(ParticipantPersona(user_id=u.id, persona_text=text))
            else:
                row.persona_text = text
            restored += 1
        await session.commit()
        summary["personas"] = {"restored": restored, "skipped": skipped}

    return summary
