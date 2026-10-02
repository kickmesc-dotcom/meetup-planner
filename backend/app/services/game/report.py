"""GHG10 Э5.4: игровые отчёты для ЧАТА (ранг, чарт, правила опыта).

Задание требует три вещи командой в чат: «свой ранг», «чарт рангов участников»
и «сообщение с описанием, за какие действия добавляется опыт». Тексты живут
здесь, а не в aiogram-хендлерах, по двум причинам:

1. их можно проверить без бота (чистые форматтеры) и переиспользовать;
2. формат чата — не формат мини-аппа: в Telegram нет CSS, поэтому прогресс
   рисуется квадратами, а ранг — текстом (цвет плашки в чат не доедешь).

Все функции-читатели возвращают `None`, если игра выключена: вызывающий код
просто молчит. Это тот же инвариант, что у `flags` — выключенная игра не
производит никакого видимого эффекта.
"""
from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameProfile, User
from app.services.game import achievements, levels, xp
from app.services.game import achievements_catalog as catalog
from app.services.game.config import (
    LEVEL_UNLOCKS,
    MAX_LEVEL,
    COMPLETIONIST_TITLE,
    SUPREME_CHUKHAN_TITLE,
    XP_CURVE_STEP,
    XP_RULES,
    feature_description,
    feature_title,
    next_unlock_level,
    unlocks_for_level,
)
from app.services.game.flags import is_game_enabled

log = structlog.get_logger()

# Ширина прогресс-бара в чате (квадраты «█»/«░»).
BAR_WIDTH = 10

# Сколько пунктов «открыто» показывать: весь список к 10 рангу раздувается до
# 11 строк и топит главное (ранг и прогресс).
UNLOCKED_PREVIEW = 4

_LIMIT_LABELS = {
    "day": "раз в день",
    "week": "раз в неделю",
    "year": "раз в год",
    "once": "только один раз",
}


def limit_label(limit: str | None) -> str:
    """Человеческая подпись лимита начисления. Чистая — тестируется без БД."""
    if limit is None:
        return ""
    return _LIMIT_LABELS.get(limit, "")


def progress_bar(filled: int, total: int, *, width: int = BAR_WIDTH) -> str:
    """Прогресс до следующего ранга квадратами.

    `total` может быть 0 (на максимуме) — тогда бар рисуем полным: «шкалы
    больше нет» честнее показывать заполненной, чем пустой.
    """
    if total <= 0:
        return "█" * width
    filled = max(0, min(filled, total))
    done = round(width * filled / total)
    return "█" * done + "░" * (width - done)


def ordinal(level: int) -> str:
    """«3-й» — для фраз про ранги. Чистая."""
    return f"{level}-й"


def level_bar_total(level: int) -> int:
    """Знаменатель шкалы прогресса для уровня — цена именно ЭТОГО перехода.

    Шкала прогрессивная, поэтому «сколько осталось до следующего ранга» зависит от
    текущего уровня: 100 XP на первом, 900 на девятом. Знаменатель берём из шкалы,
    а не из константы, иначе бар на поздних рангах всегда выглядел бы полным.
    """
    return levels.xp_span_for_level(level)


async def effective_rank_name(
    session: AsyncSession, user_id: int, profile: GameProfile | None
) -> str:
    """Имя ранга с учётом приоритетов: спец-ранг → своё название → за уровень.

    Дублирует логику профиля намеренно: чат и мини-апп обязаны показывать одно
    и то же имя, иначе «Верховный чухан» в чате и «Сигма икона» в профиле
    выглядят как баг.
    """
    total = profile.xp if profile is not None else 0
    level = levels.level_for_xp(total)
    # «Идеальный червь» (100% ачивок) — выше даже «Верховного чухана».
    if await achievements.is_completionist(session, user_id):
        return COMPLETIONIST_TITLE
    if await achievements.is_supreme_chukhan(session, user_id):
        return SUPREME_CHUKHAN_TITLE
    if profile is not None and profile.custom_rank_title:
        return profile.custom_rank_title
    return levels.rank_for_level(level).name


async def my_rank_text(
    session: AsyncSession, *, user_id: int, display_name: str
) -> str | None:
    """«Мой ранг»: ранг, шкала до следующего, дневной итог и что уже открыто."""
    if not await is_game_enabled(session):
        return None

    profile = await session.get(GameProfile, user_id)
    total = profile.xp if profile is not None else 0
    progress = levels.progress_for_xp(total)
    rank_name = await effective_rank_name(session, user_id, profile)

    lines = [
        f"🏅 <b>{display_name}</b> — {ordinal(progress.level)} ранг «{rank_name}»",
    ]

    if progress.at_max:
        lines.append(
            f"👑 Максимум взят: престиж <b>{progress.prestige}</b> XP "
            f"(всего {total})."
        )
    else:
        span = level_bar_total(progress.level)
        bar = progress_bar(progress.xp_into_level, span)
        lines.append(
            f"{bar} {progress.xp_into_level}/{span} XP "
            f"до {ordinal(progress.level + 1)} ранга — ещё <b>{progress.xp_to_next}</b>"
        )

    buckets = await xp.daily_history(session, user_id)
    today = xp.total_for_day(buckets)
    if today:
        lines.append(f"📈 Сегодня: <b>+{today}</b> XP")

    unlocked = unlocks_for_level(progress.level)
    if unlocked:
        preview = ", ".join(feature_title(code) for code in unlocked[-UNLOCKED_PREVIEW:])
        lines.append(f"🔓 Открыто: {preview}")

    if not progress.at_max:
        nxt = next_unlock_level(progress.level)
        if nxt is not None:
            codes = [
                feature_title(code) for code in LEVEL_UNLOCKS.get(nxt, ())
            ]
            if codes:
                lines.append(f"🔜 На {ordinal(nxt)} ранге: {', '.join(codes)}")
    return "\n".join(lines)


async def chart_rows(session: AsyncSession) -> list[tuple[int, str, int, str | None]] | None:
    """Данные чарта рангов: ВСЕ участники, включая без опыта.

    В отличие от мини-аппа (там чарт строится по `game_profiles`) в чате
    показываем и нулевых: список из трёх имён при шести участниках читался бы
    как «остальных выкинули», а не как «остальные не качались».

    Возвращает `(user_id, имя, опыт, своё название ранга)` по убыванию опыта.
    Своё название тянем тем же SELECT'ом: без него «/levels» показывал бы одно
    имя ранга в своей стате и другое (за уровень) — в чарте прямо под ней.
    """
    if not await is_game_enabled(session):
        return None

    rows = (
        await session.execute(
            select(
                User.id,
                User.display_name,
                GameProfile.xp,
                GameProfile.custom_rank_title,
            )
            .join(GameProfile, GameProfile.user_id == User.id, isouter=True)
            .order_by(GameProfile.xp.desc().nullslast(), User.display_name)
        )
    ).all()
    return [(int(uid), name, total or 0, title) for uid, name, total, title in rows]


def chart_lines(
    rows: list[tuple[int, str, int, str | None]], supreme: set[int]
) -> list[str]:
    """Готовые строки чарта из `chart_rows`. Чистая — тестируется без БД."""
    if not rows:
        return ["⚠️ В чате пока никто не зарегистрирован."]
    lines: list[str] = []
    for idx, (user_id, name, total, custom_title) in enumerate(rows, start=1):
        progress = levels.progress_for_xp(total)
        rank_name = levels.rank_for_level(progress.level).name
        # Приоритеты те же, что у `effective_rank_name`: спец-ранг → своё → уровень.
        if user_id in supreme:
            rank_name = SUPREME_CHUKHAN_TITLE
        elif custom_title:
            rank_name = custom_title
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"{idx}.")
        lines.append(
            f"{medal} <b>{name}</b> — {ordinal(progress.level)} «{rank_name}» · {total} XP"
        )
    return lines


async def ranks_chart_text(session: AsyncSession) -> str | None:
    """Чарт рангов участников (только чарт)."""
    rows = await chart_rows(session)
    if rows is None:
        return None
    supreme = await achievements.supreme_holders(session)
    return "\n".join(["📊 <b>Чарт рангов</b>", *chart_lines(rows, supreme)])


async def levels_text(
    session: AsyncSession, *, user_id: int, display_name: str
) -> str | None:
    """Подробная стата по СВОЕМУ левелу + левелы всех участников одним сообщением.

    Отличие от `/rank`: там коротко «где я и что открыто», здесь — цифры, место в
    чате, собранные ачивки и ИЗ ЧЕГО сложился сегодняшний опыт (берётся из
    дневного агрегата, а не из угадывания).
    """
    if not await is_game_enabled(session):
        return None

    rows = await chart_rows(session)
    profile = await session.get(GameProfile, user_id)
    total = profile.xp if profile is not None else 0
    progress = levels.progress_for_xp(total)
    rank_name = await effective_rank_name(session, user_id, profile)

    lines = [
        f"🎖 <b>{display_name}</b> — {ordinal(progress.level)} ранг «{rank_name}»"
    ]
    if progress.at_max:
        lines.append(
            f"👑 Прокачка пройдена: престиж <b>{progress.prestige}</b> XP "
            f"(всего {total})."
        )
    else:
        span = level_bar_total(progress.level)
        bar = progress_bar(progress.xp_into_level, span)
        lines.append(
            f"{bar} {progress.xp_into_level}/{span} XP "
            f"до {ordinal(progress.level + 1)} ранга — ещё <b>{progress.xp_to_next}</b>"
        )

    stats = [
        f"📊 Всего <b>{total}</b> XP",
        f"🏅 Уровень {progress.level}/{MAX_LEVEL}",
    ]
    if rows:
        place = next(
            (idx for idx, row in enumerate(rows, start=1) if row[0] == user_id),
            None,
        )
        if place is not None and len(rows) > 1:
            stats.append(f"место {place} из {len(rows)}")
    stats.append(
        f"ачивок {await achievements.count_for_user(session, user_id)}"
        f"/{catalog.catalog_size()}"
    )
    lines.append(" · ".join(stats))

    buckets = await xp.daily_history(session, user_id)
    today = xp.total_for_day(buckets)
    if today:
        top = sorted(buckets, key=lambda bucket: -bucket.points)[:3]
        sources = ", ".join(f"{b.title.lower()} ×{b.count}" for b in top)
        lines.append(f"📈 Сегодня: <b>+{today}</b> XP ({sources})")

    unlocked = unlocks_for_level(progress.level)
    if unlocked:
        preview = ", ".join(feature_title(code) for code in unlocked[-UNLOCKED_PREVIEW:])
        lines.append(f"🔓 Открыто: {preview}")
    if not progress.at_max:
        nxt = next_unlock_level(progress.level)
        codes = [feature_title(code) for code in LEVEL_UNLOCKS.get(nxt or 0, ())]
        if codes:
            lines.append(f"🔜 На {ordinal(nxt)} ранге: {', '.join(codes)}")

    supreme = await achievements.supreme_holders(session)
    lines.append("")
    lines.append("📊 <b>Левелы участников</b>")
    lines.extend(chart_lines(rows or [], supreme))
    return "\n".join(lines)


async def achievements_guide_text(
    session: AsyncSession, *, user_id: int | None = None
) -> str | None:
    """Список ВСЕХ ачивок с описаниями (и отметками того, что уже собрано).

    Юбилейные тиры не разворачиваются в отдельные абзацы: у тира то же описание,
    что у базовой ачивки (меняется только число), а 45 строк текста в чат не
    влезут и читались бы как свалка. Вместо этого у базовой ачивки есть строка
    «юбилеи: ×10 ✅ · ×20 ▫️ …» — видно и весь набор, и что уже взято.
    """
    if not await is_game_enabled(session):
        return None

    if user_id is not None and session is not None:
        # Э18: лист ачивок — хороший момент выдать капстоун за 100% коллекции.
        # Без сессии (статический справочник) коллекцию не проверяем.
        await achievements.reconcile_completionist(session, user_id)
    collected = (
        await achievements.collected_codes(session, user_id)
        if user_id is not None
        else set()
    )
    counters = (
        await achievements.progress(session, user_id)
        if user_id is not None
        else {}
    )
    # Сводка редкости — «сколько % участников имеют такую». Best-effort: подсказка
    # обязана работать и там, где сессии нет/БД отвалилась (тот же инвариант, что
    # у `xp_rules_text` — статический список без БД).
    rarity: dict[str, object] = {}
    if session is not None:
        try:
            rarity = {s.code: s for s in await achievements.rarity_stats(session)}
        except Exception as exc:  # noqa: BLE001
            log.warning("game.ach_rarity_failed", error=str(exc))
    bases = catalog.base_achievements()
    total = catalog.catalog_size()

    head = f"🏆 <b>Ачивки</b> — {len(bases)} базовых, с юбилеями {total}."
    if user_id is not None:
        head += f" У тебя: <b>{len(collected)}</b>/{total}."
    lines = [head]
    # Главная путаница, которую жаловались в чате: «С почином» берётся ОДИН раз
    # (первый лох), а «×10/×20/…» — это ОТДЕЛЬНЫЕ ачивки за юбилеи, а не
    # прогресс первой. Строка ниже говорит это прямым текстом.
    lines.append(
        "ℹ️ У накопительных ачивок две разные сущности: <b>разовая</b> берётся за "
        "первый случай, а каждый <b>юбилей</b> (×10/×20/…) — своя отдельная ачивка."
    )

    # Группируем по разделам каталога. Одним списком это была стена текста:
    # 20 строк по 150 символов, без воздуха и без опознаваемых границ (прод-
    # фидбек 29.09: «вообще нечитаемая стена»). Теперь каждый раздел — свой
    # блок: заголовок, пустая строка, и внутри ачивки разделены пустыми
    # строками, а описание ушло на отдельную строку с отбивкой.
    hidden = 0
    rendered: dict[str, list[str]] = {}
    for base in bases:
        taken = _is_collected(base.code, base.tiers, collected)
        if base.secret and not taken:
            # Служебные и капстоун-ачивки не спойлерим: иначе "Верховный чухан"
            # перестал бы быть сюрпризом для того, кто только начал качаться.
            hidden += 1
            continue
        # ✅/▫️ — получена или нет; блок внутри раздела отделён пустой строкой.
        mark = "✅" if taken else "▫️"
        block = [f"{mark} {base.icon} <b>{base.title}</b>"]
        block.append(f"    <i>{base.description}</i>")
        count = counters.get(base.code)
        if base.tiers:
            # Накопитель: разовая запись и юбилеи — разное, поэтому и подписи
            # разные. Прогресс показываем только там, где он есть (счётчик).
            one_time = "✅ взята" if base.code in collected else "▫️ пока нет"
            block.append(f"    ┗ разовая: {one_time}")
            if count is not None:
                block.append(f"    ┗ случаев: <b>{count}</b>")
            tiers = tier_marks(base.code, collected)
            if tiers:
                block.append(f"    ┗ юбилейные ачивки: {tiers}")
        elif count is not None:
            block.append(f"    ┗ сейчас: <b>{count}</b>")
        stat = rarity.get(base.code)
        if stat is not None and getattr(stat, "total", 0):
            block.append(
                f"    ┗ имеют: <b>{stat.percent}%</b> "
                f"({stat.holders}/{stat.total})"
            )
        key, _ = catalog.group_of(base.code)
        rendered.setdefault(key, []).append("\n".join(block))

    for key, title, codes in catalog.GROUPS:
        blocks = rendered.get(key)
        if not blocks:
            continue
        taken_here = 0
        for code in codes:
            ach = catalog.get(code)
            if ach is not None and _is_collected(code, ach.tiers, collected):
                taken_here += 1
        lines.append("")
        lines.append(f"<b>{title}</b>  <i>собрано {taken_here}/{len(codes)}</i>")
        lines.append("")
        lines.append("\n\n".join(blocks))

    leftovers = rendered.get(catalog.GROUP_FALLBACK[0])
    if leftovers:
        lines.append("")
        lines.append(f"<b>{catalog.GROUP_FALLBACK[1]}</b>")
        lines.append("")
        lines.append("\n\n".join(leftovers))

    lines.append("")
    if hidden:
        lines.append(f"🔒 Скрытых ачивок: {hidden} — узнаешь, когда получишь.")
    points = sorted({base.points for base in bases})
    reward = f"+{points[0]} XP"
    if len(points) > 1:
        reward += f", самая редкая — +{points[-1]}"
    lines.append(
        f"За ачивку дают {reward} — опыт идёт в тот же счёт, что ранги. "
        "«Имеют» — доля участников, у которых она уже есть."
    )
    lines.append("Свои ачивки и прогресс — в мини-аппе, раздел «🏅 Ачивки и ранги».")
    return "\n".join(lines)


def _is_collected(base_code: str, tiers: tuple[int, ...], collected: set[str]) -> bool:
    """Взята ли ачивка хоть в каком-то виде (базовая или любой её юбилей). Чистая."""
    if base_code in collected:
        return True
    return any(f"{base_code}:{tier}" in collected for tier in tiers)


def tier_marks(base_code: str, collected: set[str]) -> str:
    """«×10 ✅ · ×20 ▫️» — какие юбилеи ачивки уже взяты. Чистая (тесты)."""
    parts: list[str] = []
    for code in catalog.tier_codes(base_code):
        ach = catalog.get(code)
        if ach is None or ach.tier is None:
            continue
        parts.append(f"×{ach.tier} {'✅' if code in collected else '▫️'}")
    return " · ".join(parts)



def xp_rules_text() -> str:
    """«За что дают опыт»: таблица правил из единственной точки тюнинга.

    Чистая функция: список правил статический, БД не нужна (и не должна —
    подсказка обязана работать даже при лежащей базе).
    """
    lines = ["⚡️ <b>За что дают опыт</b>"]
    for rule in XP_RULES.values():
        label = limit_label(rule.limit)
        tail = f" <i>({label})</i>" if label else ""
        price = "по событию" if rule.variable else f"<b>+{rule.points}</b> XP"
        lines.append(f"• {rule.title} — {price}{tail}")
    lines.append(
        f"\nШкала прогрессивная: 1→2 ранг стоит {XP_CURVE_STEP} XP, каждый следующий "
        f"дороже на {XP_CURVE_STEP} (100 / 200 / 300 / …), а на {MAX_LEVEL}-й ранг — "
        "около 1000 XP. Дальше опыт идёт в престиж."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Э13: мини-методичка — «как всё работает» одним сообщением
# --------------------------------------------------------------------------


def manual_xp_block() -> list[str]:
    """Строки про опыт — из единственной точки тюнинга, чтобы не разъехались."""
    out: list[str] = []
    for rule in XP_RULES.values():
        label = limit_label(rule.limit)
        tail = f" ({label})" if label else ""
        price = "по событию" if rule.variable else f"+{rule.points} XP"
        out.append(f"• {rule.title} — {price}{tail}")
    return out


def _first_sentence(text: str) -> str:
    """Первое предложение описания — для компактной памятки в чате. Чистая."""
    if not text:
        return ""
    head = text.split(". ", 1)[0]
    return head.rstrip(".")


def manual_ranks_block() -> list[str]:
    """Что открывает каждый ранг — человеческим языком, из `FEATURE_DESCRIPTIONS`.

    Оператор: «описать куда зайти, что нажать и что будет». Поэтому в памятке
    не сухое название, а первое предложение объяснения (полное — в профиле/на
    уведомлении о ранге), иначе `/game` читался как список терминов.
    """
    out: list[str] = []
    for level in sorted(LEVEL_UNLOCKS):
        for code in LEVEL_UNLOCKS[level]:
            hint = _first_sentence(feature_description(code))
            tail = f": {hint}" if hint else ""
            out.append(f"• {level} ранг — {feature_title(code)}{tail}")
    return out


async def game_manual_text(session: AsyncSession) -> str | None:
    """Мини-методичка «что тут вообще происходит» — по команде /game.

    Собирается из тех же структур, что и сама игра (`XP_RULES`, `LEVEL_UNLOCKS`,
    каталоги событий и слов), поэтому не может «рассказать одно, а делать
    другое». `None` — игра выключена, отвечать нечего.
    """
    if not await is_game_enabled(session):
        return None

    from app.services.admin_config import (
        get_game_contraband_enabled,
        get_game_digest_enabled,
        get_game_digest_interval_hours,
        get_game_events_enabled,
        get_game_memorial_enabled,
        get_game_memorial_silence_days,
    )
    from app.services.game import contraband
    from app.services.game.events_catalog import PROMPTS

    def _on(flag: bool) -> str:
        return "включено" if flag else "выключено"

    lines: list[str] = ["📖 <b>Игра: как всё работает</b>"]

    lines.append("\n<b>Опыт</b>")
    lines.extend(manual_xp_block())

    lines.append(
        f"\n<b>Уровни.</b> {MAX_LEVEL} уровней, шкала прогрессивная: первые шаги по "
        f"{XP_CURVE_STEP} XP, переход на {MAX_LEVEL}-й ранг — ≈1000 XP. Уровень = "
        f"ранг. С {MAX_LEVEL}-го опыт идёт в престиж, качаться больше некуда."
    )
    lines.append("<b>Что открывает ранг</b>")
    lines.extend(manual_ranks_block())

    lines.append(
        f"\n<b>Ачивки</b> — {len(catalog.CATALOG)} шт., каждая берётся один раз. "
        "У накопительных есть юбилеи (×10/20/30/50/100), у «С почином» за ×100 — "
        f"титул «{SUPREME_CHUKHAN_TITLE}» поверх ранга. Список: /ach"
    )

    lines.append(
        f"\n<b>Случайные события</b> — {_on(await get_game_events_enabled(session))}. "
        "Бот иногда кидает призыв в чат; первый, кто ответит, забирает XP:"
    )
    for prompt in PROMPTS:
        first = (prompt.text or "").split("\n")[0]
        clean = _strip_tags(first)
        lines.append(f"• {clean} ({prompt.ttl_minutes} мин)")

    words = await contraband.configured_words(session)
    lines.append(
        f"\n<b>Контрабанда слов</b> — {_on(await get_game_contraband_enabled(session))}. "
        "Опыт за кодовое слово уходит ВЛАДЕЛЬЦУ (не тому, кто написал):"
    )
    for entry in words:
        if not entry.get("enabled", True):
            continue
        owner = entry.get("owner") or "—"
        lines.append(f"• «{entry.get('word')}» → <b>{owner}</b> (+{entry.get('xp', 0)} XP)")

    silence = await get_game_memorial_silence_days(session)
    lines.append(
        f"\n<b>Поминовения</b> — {_on(await get_game_memorial_enabled(session))}. "
        f"Молчишь {silence} дней — бот торжественно поминает, вернёшься — «ОН ЗДЕСЬ»."
    )

    digest = await get_game_digest_enabled(session)
    every = await get_game_digest_interval_hours(session)
    lines.append(
        f"\n<b>Сводка</b> — {_on(digest)} (сейчас раз в {every} ч). "
        "Пока выключена, бот пишет про ачивки сразу; включённая — копит в журнал и "
        "вываливает одним сообщением раз в 1/6/12/24 ч."
    )

    lines.append("\n<b>Команды</b> — простыми словами:")
    lines.extend(
        [
            "• /rank — твой ранг и сколько XP до следующего",
            "• /ranks — кто на каком ранге (чарт)",
            "• /levels — подробная стата и опыт всех",
            "• /xp — за что капает опыт",
            "• /ach — все ачивки и что уже собрано",
            "• /loser — ручная рулетка: крутануть лоха вручную (со 2 ранга)",
            "• /meetings — кто когда свободен и встречи",
            "• /top — топ по сообщениям",
            "• /tasks — что бот умеет по заданиям",
            "• /nominate — предложить игру в голосование",
            "• /punish — наказать недруга (если включён режим «червь-господин»)",
            "• /отвали — попросить бота отстать",
            "• /game — эта памятка",
        ]
    )
    return "\n".join(lines)


# Лимит Telegram — 4096 символов. Оставляем запас на HTML-теги/эмодзи.
CHAT_MESSAGE_LIMIT = 4000


def chunk_text(text: str, *, limit: int = CHAT_MESSAGE_LIMIT) -> list[str]:
    """Порезать длинный текст на сообщения по границам строк. Чистая функция.

    Нужна там, где справочник может перерасти одно сообщение: отдавать
    «Bad Request: message is too long» вместо ответа — худший вариант.
    """
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _strip_tags(text: str) -> str:
    """Убрать HTML-теги из строки — для цитирования каталогов в методичке."""
    import re

    return re.sub(r"<[^>]+>", "", text).strip()
