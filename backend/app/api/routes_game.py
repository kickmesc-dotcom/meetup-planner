"""GHG10 Э5: поверхности игровой системы (профиль, чарты рангов и ачивок).

Один роутер — потому что все ответы про одно: «что у меня и у остальных в игре».
Рубильник соблюдается мягко: при `game.enabled=false` профиль отвечает
`{enabled: false}` (мини-апп просто прячет игровые блоки), а чарты — пустой
список. Ошибки НЕ бросаем: выключенная игра — не ошибка.

Тяжёлые агрегаты — по одному SELECT (`achievements.leaderboard`,
`supreme_holders`, `GameProfile.xp desc`), без N+1 (требование Э12.1).
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.config import get_settings
from app.db.models import GameProfile, User, UserAchievement
from app.schemas.game import (
    AchievementHolderOut,
    AchievementItemOut,
    DailyEventOut,
    DonationIn,
    DonationOut,
    FeatureOut,
    GameCustomizePatch,
    GameProfileOut,
    HolidayCreate,
    HolidayOut,
    HolidaysOut,
    LevelUpOut,
    RankOut,
    RankRowOut,
    XpRuleOut,
)
from app.services.game import achievements, donations, gates, holidays, levels, xp
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

log = structlog.get_logger()

# Код фичи-праздников в `LEVEL_UNLOCKS` (открывается с 6 ранга).
FEATURE_HOLIDAYS = "holidays_manage"

# Код отказа доната → HTTP-статус. 409 — «уже было/нельзя сейчас», 400 — «нельзя
# в принципе»: фронт показывает разные подсказки, поэтому коды не смешиваем.
_DONATION_STATUS = {
    donations.SELF_DONATION: status.HTTP_400_BAD_REQUEST,
    donations.NOT_BIRTHDAY: status.HTTP_409_CONFLICT,
    donations.ALREADY_DONATED: status.HTTP_409_CONFLICT,
    donations.NOT_ENOUGH_XP: status.HTTP_400_BAD_REQUEST,
}

# Таймаут насмешки в чат (см. `_tease_in_chat`): как у остальных TG-вызовов из
# API — не блокируем webhook дольше сессии.
_TEASE_TIMEOUT = 15.0


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


# --------------------------------------------------------------------------
# Э11: донат опыта имениннику
# --------------------------------------------------------------------------


async def _tease_in_chat(display_name: str, *, xp_now: int) -> None:
    """Насмешка в общий чат над попыткой задонатить то, чего нет (спека Э11).

    Best-effort и с таймаутом: кнопка в мини-аппе не должна зависеть от того,
    сможет ли бот сейчас написать в группу (РКН/троттлинг — регулярная история).
    """
    settings = get_settings()
    if not settings.group_chat_id:
        return
    from app.bot.dispatcher import get_bot

    text = donations.teasing_message(display_name, xp_now=xp_now)
    try:
        await asyncio.wait_for(
            get_bot().send_message(
                chat_id=settings.group_chat_id, text=text, parse_mode="HTML"
            ),
            timeout=_TEASE_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("game.donation_tease_failed", error=str(exc))


@router.post("/game/donate", response_model=DonationOut)
async def donate_xp(
    body: DonationIn, session: SessionDep, user: CurrentUser
) -> DonationOut:
    """Подарить 100 XP имениннику, списав свои (кнопка у тортика в ДР)."""
    if not await is_game_enabled(session):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "game_disabled")

    if body.user_id is None and body.telegram_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "recipient_required")
    if body.user_id is not None:
        recipient = await session.get(User, body.user_id)
    else:
        recipient = await session.scalar(
            select(User).where(User.telegram_id == body.telegram_id)
        )
    if recipient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")

    res = await donations.donate(
        session, donor_id=user.id, recipient_id=recipient.id
    )
    if not res.ok:
        if res.code == donations.NOT_ENOUGH_XP:
            # Спека: «можно высмеять в чат такую наивную попытку».
            await _tease_in_chat(user.display_name, xp_now=res.donor_xp)
        raise HTTPException(
            _DONATION_STATUS.get(res.code, status.HTTP_400_BAD_REQUEST), res.code
        )

    return DonationOut(
        ok=True,
        code=res.code,
        amount=res.amount,
        donor_xp=res.donor_xp,
        recipient_xp=res.recipient_xp,
        recipient_name=recipient.display_name,
    )


@router.get("/game/achievements", response_model=list[AchievementHolderOut])
async def achievements_chart(
    session: SessionDep, _: CurrentUser
) -> list[AchievementHolderOut]:
    """Чарт обладателей ачивок: кто сколько собрал (Э5.3)."""
    if not await is_game_enabled(session):
        return []
    rows = await achievements.leaderboard(session)
    return [AchievementHolderOut(user_id=uid, count=cnt) for uid, cnt in rows]


# --------------------------------------------------------------------------
# Э10.3: пул праздников — «дата + сообщение»
# --------------------------------------------------------------------------


def _holiday_out(row) -> HolidayOut:
    return HolidayOut(
        id=row.id,
        month=row.month,
        day=row.day,
        message=row.message,
        enabled=row.enabled,
    )


@router.get("/game/holidays", response_model=HolidaysOut)
async def holidays_list(session: SessionDep, user: CurrentUser) -> HolidaysOut:
    """Список праздников + можно ли править (по заданию — с 6 ранга или админу).

    Читать можно всем: праздник влияет на всех (+50 XP всему чату), поэтому
    состав пула не секрет. Править — по гейту `holidays_manage`.
    """
    if not await is_game_enabled(session):
        return HolidaysOut()
    gate = await gates.check_feature(
        session, FEATURE_HOLIDAYS, user_id=user.id, telegram_id=user.telegram_id
    )
    rows = await holidays.list_holidays(session)
    return HolidaysOut(
        can_manage=gate.allowed,
        required_level=gate.required_level,
        items=[_holiday_out(row) for row in rows],
    )


@router.post(
    "/game/holidays",
    response_model=HolidayOut,
    status_code=status.HTTP_201_CREATED,
)
async def holiday_add(
    body: HolidayCreate, session: SessionDep, user: CurrentUser
) -> HolidayOut:
    """Добавить праздник (гейт `holidays_manage`, Э10.3)."""
    if not await is_game_enabled(session):
        # У выключенной игры нет и её функций: иначе праздник завели бы в пустоту
        # (job не работает, опыт не начисляется) и он бы «выстрелил» потом.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "game_disabled")
    await gates.require_feature(session, user, FEATURE_HOLIDAYS)
    try:
        row = await holidays.add_holiday(
            session,
            month=body.month,
            day=body.day,
            message=body.message,
            created_by_user_id=user.id,
        )
    except holidays.HolidayError as exc:
        # Занятая дата — это конфликт, кривой ввод — 400: фронт показывает разные
        # подсказки, поэтому коды должны различаться. Пересказ в текст — на клиенте.
        code = (
            status.HTTP_409_CONFLICT
            if exc.code == "holiday_date_taken"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(code, exc.code) from exc
    return _holiday_out(row)


@router.delete("/game/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
async def holiday_delete(
    holiday_id: int, session: SessionDep, user: CurrentUser
) -> Response:
    """Убрать праздник. Гейт тот же, что на добавление (одно право — обе ручки)."""
    if not await is_game_enabled(session):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "game_disabled")
    await gates.require_feature(session, user, FEATURE_HOLIDAYS)
    if not await holidays.remove_holiday(session, holiday_id=holiday_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "holiday_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
