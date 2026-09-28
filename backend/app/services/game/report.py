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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameProfile, User
from app.services.game import achievements, levels, xp
from app.services.game.config import (
    LEVEL_UNLOCKS,
    MAX_LEVEL,
    SUPREME_CHUKHAN_TITLE,
    XP_PER_LEVEL,
    XP_RULES,
    feature_title,
    next_unlock_level,
    unlocks_for_level,
)
from app.services.game.flags import is_game_enabled

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
        bar = progress_bar(progress.xp_into_level, XP_PER_LEVEL)
        lines.append(
            f"{bar} {progress.xp_into_level}/{XP_PER_LEVEL} XP "
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


async def ranks_chart_text(session: AsyncSession) -> str | None:
    """Чарт рангов для чата: ВСЕ участники, включая без опыта.

    В отличие от мини-аппа (там чарт строится по `game_profiles`) в чате
    показываем и нулевых: список из трёх имён при шести участниках читался бы
    как «остальных выкинули», а не как «остальные не качались».
    """
    if not await is_game_enabled(session):
        return None

    rows = (
        await session.execute(
            select(User.id, User.display_name, GameProfile.xp)
            .join(GameProfile, GameProfile.user_id == User.id, isouter=True)
            .order_by(GameProfile.xp.desc().nullslast(), User.display_name)
        )
    ).all()
    if not rows:
        return "📊 В чате пока никто не зарегистрирован."

    supreme = await achievements.supreme_holders(session)
    lines = ["📊 <b>Чарт рангов</b>"]
    for idx, (user_id, name, total) in enumerate(rows, start=1):
        total = total or 0
        progress = levels.progress_for_xp(total)
        rank_name = levels.rank_for_level(progress.level).name
        if user_id in supreme:
            rank_name = SUPREME_CHUKHAN_TITLE
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"{idx}.")
        lines.append(
            f"{medal} <b>{name}</b> — {ordinal(progress.level)} «{rank_name}» · {total} XP"
        )
    return "\n".join(lines)


def xp_rules_text() -> str:
    """«За что дают опыт»: таблица правил из единственной точки тюнинга.

    Чистая функция: список правил статический, БД не нужна (и не должна —
    подсказка обязана работать даже при лежащей базе).
    """
    lines = ["⚡️ <b>За что дают опыт</b>"]
    for rule in XP_RULES.values():
        label = limit_label(rule.limit)
        tail = f" <i>({label})</i>" if label else ""
        lines.append(f"• {rule.title} — <b>+{rule.points}</b> XP{tail}")
    lines.append(
        f"\n1 ранг = 100 XP, максимум — {MAX_LEVEL}. Дальше опыт идёт в престиж."
    )
    return "\n".join(lines)
