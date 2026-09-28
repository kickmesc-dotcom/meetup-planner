"""GHG10 Э5: поверхности игровой системы (профиль, чарты рангов и ачивок).

Один роутер — потому что все ответы про одно: «что у меня и у остальных в игре».
Рубильник соблюдается мягко: при `game.enabled=false` профиль отвечает
`{enabled: false}` (мини-апп просто прячет игровые блоки), а чарты — пустой
список. Ошибки НЕ бросаем: выключенная игра — не ошибка.

Тяжёлые агрегаты — по одному SELECT (`achievements.leaderboard`,
`supreme_holders`, `GameProfile.xp desc`), без N+1 (требование Э12.1).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.db.models import GameProfile, UserAchievement
from app.schemas.game import (
    AchievementHolderOut,
    AchievementItemOut,
    DailyEventOut,
    FeatureOut,
    GameCustomizePatch,
    GameProfileOut,
    LevelUpOut,
    RankOut,
    RankRowOut,
    XpRuleOut,
)
from app.services.game import achievements, gates, levels, xp
from app.services.game.achievements_catalog import base_achievements
from app.services.game.config import (
    MAX_LEVEL,
    SUPREME_CHUKHAN_TITLE,
    XP_RULES,
    feature_title,
    unlocks_between,
    unlocks_for_level,
)
from app.services.game.flags import is_game_enabled

router = APIRouter(tags=["game"])


def _rank_out(level: int) -> RankOut:
    rank = levels.rank_for_level(level)
    return RankOut(level=rank.level, name=rank.name, hex=rank.hex, bold=rank.bold)


async def _unlocked_at_map(
    session: AsyncSession, user_id: int
) -> dict[str, datetime]:
    """Код ачивки → когда получена (для листа). Тир-коды тоже здесь."""
    rows = (
        await session.scalars(
            select(UserAchievement).where(UserAchievement.user_id == user_id)
        )
    ).all()
    return {row.code: row.unlocked_at for row in rows}


@router.get("/me/game", response_model=GameProfileOut)
async def my_game(session: SessionDep, user: CurrentUser) -> GameProfileOut:
    """Полный игровой профиль: ранг + шкала/престиж + день + лист ачивок."""
    if not await is_game_enabled(session):
        return GameProfileOut(enabled=False, level=1, max_level=MAX_LEVEL)

    profile = await session.get(GameProfile, user.id)
    total_xp = profile.xp if profile is not None else 0
    progress = levels.progress_for_xp(total_xp)

    supreme = await achievements.is_supreme_chukhan(session, user.id)
    rank_name = progress.rank.name
    if supreme:
        # Э3.4: спец-ранг приоритетнее ранга за уровень.
        rank_name = SUPREME_CHUKHAN_TITLE
    elif profile is not None and profile.custom_rank_title:
        rank_name = profile.custom_rank_title

    level_up: LevelUpOut | None = None
    if (
        profile is not None
        and profile.pending_level_up_from is not None
        and profile.pending_level_up_to is not None
    ):
        frm, to = profile.pending_level_up_from, profile.pending_level_up_to
        level_up = LevelUpOut(
            from_level=frm,
            from_rank=levels.rank_for_level(frm).name,
            to_level=to,
            to_rank=levels.rank_for_level(to).name,
            unlocked=[
                FeatureOut(code=code, title=feature_title(code))
                for code in unlocks_between(frm, to)
            ],
        )

    buckets = await xp.daily_history(session, user.id)
    today = [
        DailyEventOut(event=b.event, title=b.title, points=b.points, count=b.count)
        for b in buckets
    ]

    collected = await achievements.collected_codes(session, user.id)
    counters = await achievements.progress(session, user.id)
    unlocked_at = await _unlocked_at_map(session, user.id)
    items: list[AchievementItemOut] = []
    for ach in base_achievements():
        items.append(
            AchievementItemOut(
                code=ach.code,
                title=ach.title,
                description=ach.description,
                icon=ach.icon,
                points=ach.points,
                kind=ach.kind,
                collected=ach.code in collected,
                unlocked_at=unlocked_at.get(ach.code),
                progress=counters.get(ach.code),
                threshold=ach.threshold,
                tiers=list(ach.tiers),
            )
        )

    return GameProfileOut(
        enabled=True,
        xp=total_xp,
        level=progress.level,
        max_level=MAX_LEVEL,
        rank=_rank_out(progress.level),
        rank_name=rank_name,
        supreme=supreme,
        custom_rank_title=profile.custom_rank_title if profile is not None else None,
        xp_into_level=progress.xp_into_level,
        xp_to_next=progress.xp_to_next,
        at_max=progress.at_max,
        prestige=progress.prestige,
        custom_name=profile.custom_name if profile is not None else None,
        avatar_manual_url=getattr(user, "avatar_manual_url", None),
        unlocked=[
            FeatureOut(code=code, title=feature_title(code))
            for code in unlocks_for_level(progress.level)
        ],
        level_up=level_up,
        today=today,
        today_total=xp.total_for_day(buckets),
        achievements=items,
        xp_rules=[
            XpRuleOut(code=r.code, title=r.title, points=r.points, limit=r.limit)
            for r in XP_RULES.values()
        ],
    )


def _clean_text(value: str | None) -> str | None:
    """Пробелы по краям срезаем; пустое → None (значит «убрать своё»)."""
    if value is None:
        return None
    value = value.strip()
    return value or None


@router.patch("/me/game/profile", response_model=GameProfileOut)
async def update_profile(
    body: GameCustomizePatch, session: SessionDep, user: CurrentUser
) -> GameProfileOut:
    """Своё имя / своё название ранга / своя аватарка — каждое по своему рангу.

    Гейт стоит на КАЖДОЕ поле отдельно (см. `LEVEL_UNLOCKS`): можно дорос ти до
    аватарки (6), но не до имени (8) — аватарка сохранится, имя отклонится 403.
    Возвращаем полный профиль, чтобы клиент одним ответом обновил весь блок.
    """
    data = body.model_dump(exclude_unset=True)
    if not data:
        return await my_game(session, user)

    profile = await session.get(GameProfile, user.id)
    if profile is None:
        profile = GameProfile(user_id=user.id, xp=0)
        session.add(profile)

    if "custom_name" in data:
        await gates.require_feature(session, user, "custom_name")
        profile.custom_name = _clean_text(data["custom_name"])
    if "custom_rank_title" in data:
        await gates.require_feature(session, user, "custom_rank")
        profile.custom_rank_title = _clean_text(data["custom_rank_title"])
    if "avatar_manual_url" in data:
        await gates.require_feature(session, user, "custom_avatar")
        user.avatar_manual_url = _clean_text(data["avatar_manual_url"])

    await session.commit()
    return await my_game(session, user)


@router.post("/me/game/level-up/ack", status_code=status.HTTP_204_NO_CONTENT)
async def ack_level_up(session: SessionDep, user: CurrentUser) -> Response:
    """«Понятно»: убрать уведомление о левел-апе из профиля (идемпотентно)."""
    profile = await session.get(GameProfile, user.id)
    if profile is not None:
        profile.pending_level_up_from = None
        profile.pending_level_up_to = None
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/game/achievements", response_model=list[AchievementHolderOut])
async def achievements_chart(
    session: SessionDep, _: CurrentUser
) -> list[AchievementHolderOut]:
    """Чарт обладателей ачивок: кто сколько собрал (Э5.3)."""
    if not await is_game_enabled(session):
        return []
    rows = await achievements.leaderboard(session)
    return [AchievementHolderOut(user_id=uid, count=cnt) for uid, cnt in rows]


@router.get("/game/ranks", response_model=list[RankRowOut])
async def ranks_chart(session: SessionDep, _: CurrentUser) -> list[RankRowOut]:
    """Чарт рангов: у кого какой уровень и ранг (Э5.4)."""
    if not await is_game_enabled(session):
        return []
    profiles = (
        await session.scalars(select(GameProfile).order_by(GameProfile.xp.desc()))
    ).all()
    supreme = await achievements.supreme_holders(session)
    out: list[RankRowOut] = []
    for profile in profiles:
        prog = levels.progress_for_xp(profile.xp)
        name = prog.rank.name
        is_supreme = profile.user_id in supreme
        if is_supreme:
            name = SUPREME_CHUKHAN_TITLE
        elif profile.custom_rank_title:
            name = profile.custom_rank_title
        out.append(
            RankRowOut(
                user_id=profile.user_id,
                xp=profile.xp,
                level=prog.level,
                rank_name=name,
                hex=prog.rank.hex,
                bold=prog.rank.bold,
                supreme=is_supreme,
            )
        )
    return out
