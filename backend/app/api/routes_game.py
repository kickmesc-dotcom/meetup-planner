"""GHG10 Э5: поверхности игровой системы (профиль, чарты рангов и ачивок).

Один роутер — потому что все ответы про одно: «что у меня и у остальных в игре».
Рубильник соблюдается мягко: при `game.enabled=false` профиль отвечает
`{enabled: false}` (мини-апп просто прячет игровые блоки), а чарты — пустой
список. Ошибки НЕ бросаем: выключенная игра — не ошибка.

Тяжёлые агрегаты — по одному SELECT (`achievements.rarity_stats`,
`supreme_holders`, `GameProfile.xp desc`), без N+1 (требование Э12.1).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.config import get_settings
from app.db.models import (
    GameProfile,
    GamePrompt,
    GameVoiceSubmission,
    GameVoiceTask,
    User,
    UserAchievement,
)
from app.schemas.game import (
    AchievementItemOut,
    AchievementStatOut,
    ActivitiesOut,
    ActivityAnswerIn,
    ActivityAnswerOut,
    ActivityOptionOut,
    ActivityOut,
    DailyEventOut,
    DonationIn,
    DonationOut,
    FeatureOut,
    FeedItemOut,
    FeedOut,
    GameCustomizePatch,
    GameProfileOut,
    GuestAchievementOut,
    GuestProfileOut,
    HolidayCreate,
    HolidayOut,
    HolidaysOut,
    LevelUpOut,
    MusicAddIn,
    MusicAddOut,
    MusicLikeOut,
    MusicMineOut,
    MusicMineTrackOut,
    MusicSelectionOut,
    MusicTopTrackOut,
    MusicWeekOut,
    MusicWeekTrackOut,
    RankOut,
    RankRowOut,
    VoiceCurrentOut,
    VoiceSubmissionOut,
    VoiceSubmitOut,
    XpRuleOut,
)
from app.services.game import (
    achievements,
    donations,
    events,
    feed,
    gates,
    holidays,
    levels,
    xp,
)
from app.services.game.achievements_catalog import COMPLETIONIST_CODE, base_achievements
from app.services.game.config import (
    MAX_LEVEL,
    COMPLETIONIST_TITLE,
    SUPREME_CHUKHAN_TITLE,
    XP_RULES,
    feature_description,
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

# Э21: верхний размер голосового, принятого из мини-аппа (12 МБ — с запасом на
# минуту opus). Файлы НЕ храним: пересылаем боту, берём file_id и отдаём его.
_VOICE_MAX_BYTES = 12 * 1024 * 1024

# Э21: статусы сдачи голосового в мини-аппе → текст (фронт не парсит коды).
_VOICE_STATUS = {
    "ok": "принято",
    "no_task": "задание уже закрыто",
    "closed": "приём закрыт",
    "already": "ты уже сдавал вариант",
    "late": "награду забрал первый",
    "silent": "ты опоздал",
    "unknown_user": "ты не в списке участников",
}


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
    # Э18: коллекция загружается и так — здесь же выдаём капстоун «Идеальный червь».
    completionist = await achievements.reconcile_completionist(session, user.id)
    rank_name = progress.rank.name
    if completionist:
        # Э18: 100% ачивок — особый титул выше даже «Верховного чухана».
        rank_name = COMPLETIONIST_TITLE
    elif supreme:
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
                FeatureOut(
                    code=code,
                    title=feature_title(code),
                    description=feature_description(code),
                )
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
                collected_tiers=[
                    tier for tier in ach.tiers if f"{ach.code}:{tier}" in collected
                ],
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
        completionist=completionist,
        custom_rank_title=profile.custom_rank_title if profile is not None else None,
        xp_into_level=progress.xp_into_level,
        xp_to_next=progress.xp_to_next,
        at_max=progress.at_max,
        prestige=progress.prestige,
        custom_name=profile.custom_name if profile is not None else None,
        avatar_manual_url=getattr(user, "avatar_manual_url", None),
        unlocked=[
            FeatureOut(
                code=code,
                title=feature_title(code),
                description=feature_description(code),
            )
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


@router.get("/game/achievements", response_model=list[AchievementStatOut])
async def achievements_stats(
    session: SessionDep, _: CurrentUser
) -> list[AchievementStatOut]:
    """Насколько редка каждая ачивка — «её имеют N% участников» (Э5.3).

    Было «кто сколько собрал» списком имён; по заданию это заменено крохотной
    сводкой: две агрегации (всего участников + обладатели по кодам), без N+1.
    """
    if not await is_game_enabled(session):
        return []
    from app.services.game import achievements_catalog as catalog

    out: list[AchievementStatOut] = []
    for stat in await achievements.rarity_stats(session):
        ach = catalog.get(stat.code)
        out.append(
            AchievementStatOut(
                code=stat.code,
                title=ach.title if ach else stat.code,
                icon=ach.icon if ach else "🏆",
                holders=stat.holders,
                total=stat.total,
                percent=stat.percent,
            )
        )
    return out


# --------------------------------------------------------------------------
# Э10.3: пул праздников — «дата + сообщение»
# --------------------------------------------------------------------------


def _is_admin(user) -> bool:
    """Админ (ADMIN_TG_IDS) — правит праздники независимо от ранга.

    Так это и было задумано в справке («с 6 ранга ИЛИ админу»), но гейт про
    админов не знал: `gates` видит только «Серж нео» (отладочные TG-id). Оператор
    без 6 ранга не мог завести праздник в том самом блоке, который сам просил.
    """
    return user.telegram_id in get_settings().admin_tg_id_set


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
        can_manage=gate.allowed or _is_admin(user),
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
    if not _is_admin(user):
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
    if not _is_admin(user):
        await gates.require_feature(session, user, FEATURE_HOLIDAYS)
    if not await holidays.remove_holiday(session, holiday_id=holiday_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "holiday_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/game/players/{user_id}", response_model=GuestProfileOut)
async def guest_profile(
    user_id: int, session: SessionDep, _: CurrentUser
) -> GuestProfileOut:
    """Э19: чужой игровой профиль «глазами гостя».

    Отдаёт только факты: ранг, XP, число лохов/чуханов, место в чарте и
    собранные ачивки. Никакой кастомизации/настроек из своего профиля здесь нет
    — гость смотрит, но не правит. Зовётся из мини-аппа кликом по аватарке
    участника на календаре.
    """
    from app.services.chukhan import chukhan_stats
    from app.services.loser import loser_stats

    # Мини-апп ходит по ВНУТРЕННему id (как `/api/users` и чарт рангов), но
    # принимаем и TG-id запасным ключом — чтобы ручку можно было дёрнуть curl'ом.
    user = await session.get(User, user_id)
    if user is None:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player_not_found")
    if not await is_game_enabled(session):
        return GuestProfileOut(
            enabled=False,
            telegram_id=user.telegram_id,
            user_id=user.id,
            name=user.display_name,
        )

    profile = await session.get(GameProfile, user.id)
    total_xp = profile.xp if profile is not None else 0
    progress = levels.progress_for_xp(total_xp)
    supreme = await achievements.is_supreme_chukhan(session, user.id)
    completionist = await achievements.has(session, user.id, COMPLETIONIST_CODE)
    rank_name = progress.rank.name
    if completionist:
        rank_name = COMPLETIONIST_TITLE
    elif supreme:
        rank_name = SUPREME_CHUKHAN_TITLE
    elif profile is not None and profile.custom_rank_title:
        rank_name = profile.custom_rank_title

    rows = (
        await session.scalars(
            select(GameProfile.user_id, GameProfile.xp).order_by(GameProfile.xp.desc())
        )
    ).all()
    ranks_total = len(rows)
    rank_position = next(
        (i for i, row in enumerate(rows, start=1) if int(row[0]) == user.id), None
    )

    loser_count = int((await loser_stats(session)).get(user.id, 0))
    chukhan_count = int((await chukhan_stats(session)).get(user.id, 0))

    collected = await achievements.collected_codes(session, user.id)
    bases = base_achievements()
    items = [
        GuestAchievementOut(code=ach.code, title=ach.title, icon=ach.icon)
        for ach in bases
        if ach.code in collected
    ]

    return GuestProfileOut(
        enabled=True,
        telegram_id=user.telegram_id,
        user_id=user.id,
        name=user.display_name,
        avatar_url=getattr(user, "avatar_manual_url", None) or getattr(user, "avatar_url", None),
        level=progress.level,
        rank=_rank_out(progress.level),
        rank_name=rank_name,
        xp=total_xp,
        prestige=progress.prestige,
        supreme=supreme,
        completionist=completionist,
        loser_count=loser_count,
        chukhan_count=chukhan_count,
        rank_position=rank_position,
        ranks_total=ranks_total,
        achievements_collected=len(items),
        achievements_total=len(bases),
        achievements=items,
    )


@router.get("/game/feed", response_model=FeedOut)
async def activity_feed(
    session: SessionDep,
    user: CurrentUser,
    scope: str = Query("all", pattern="^(all|mine)$"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    kinds: str | None = Query(
        None, description="фильтр по типам через запятую (achievement,voice,...)"
    ),
) -> FeedOut:
    """Э20/Э21: лента активности — «кто что открыл и с кем что случилось».

    Главная поверхность двух софт-режимов приглушения: в режиме «ачивки в
    приложение» сюда уезжают ачивки, в режиме «всё в приложение» — вообще вся
    активность. Но ручка работает и в обычном режиме (просто дублирует чат).

    `scope=mine` — только записи текущего игрока; `limit`/`offset` — страницы;
    `kinds` — фильтр по типам записей через запятую (Э21).
    """
    if not await is_game_enabled(session):
        return FeedOut(enabled=False, items=[], kinds=[])
    wanted = (
        {k.strip() for k in kinds.split(",") if k.strip()} if kinds else None
    )
    items = await feed.build_feed(
        session,
        user_id=user.id if scope == "mine" else None,
        limit=limit,
        offset=offset,
        kinds=wanted,
    )
    return FeedOut(
        enabled=True,
        items=[FeedItemOut(**item) for item in items],
        next_offset=(offset + limit) if len(items) == limit else None,
        kinds=list(feed.FEED_KIND_ORDER),
    )


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


# --------------------------------------------------------------------------
# Э15/Э16: «Предложка недели» в мини-аппе
# --------------------------------------------------------------------------


@router.get("/game/music/mine", response_model=MusicMineOut)
async def my_music(session: SessionDep, user: CurrentUser) -> MusicMineOut:
    """Свои сданные треки, остаток недельного лимита и история подборок.

    Только для участника: чужие треки до публикации не показываем (интрига).
    Фича появляется вместе с игрой: при `game.enabled=false` экран прячется,
    как и остальные игровые блоки.
    """
    from app.services.admin_config import get_game_music_enabled
    from app.services.game import music
    from app.services.game.config import MUSIC_PER_USER_WEEKLY

    if not await is_game_enabled(session):
        return MusicMineOut(enabled=False, per_user_weekly=MUSIC_PER_USER_WEEKLY)
    enabled = await get_game_music_enabled(session)
    if not enabled:
        return MusicMineOut(enabled=False, per_user_weekly=MUSIC_PER_USER_WEEKLY)

    now = datetime.now(timezone.utc)
    tracks = await music.my_week_tracks(session, user.id, at=now)
    count = await music.weekly_count(session, user.id, at=now)
    history = await music.published_selections(session, limit=10)

    # Э17: свежая подборка с лайками — то, под чем участник и ставит реакции.
    week: MusicWeekOut | None = None
    latest = await music.latest_published_selection(session)
    if latest is not None:
        sel_tracks = await music.selection_tracks(session, latest.id)
        ids = [t.id for t in sel_tracks]
        likes = await music.like_counts(session, ids)
        mine = await music.liked_track_ids(session, user.id, ids)
        week = MusicWeekOut(
            id=latest.id,
            created_at=latest.created_at,
            track_count=latest.track_count,
            tracks=[
                MusicWeekTrackOut(
                    id=t.id,
                    kind=t.kind,
                    title=t.title,
                    performer=t.performer,
                    url=t.url,
                    likes=likes.get(t.id, 0),
                    liked=t.id in mine,
                )
                for t in sel_tracks
            ],
        )

    top_rows = await music.top_tracks(session, since=music.top_window_start(now))

    return MusicMineOut(
        enabled=True,
        per_user_weekly=MUSIC_PER_USER_WEEKLY,
        week_count=count,
        tracks=[
            MusicMineTrackOut(
                id=t.id,
                kind=t.kind,
                title=t.title,
                performer=t.performer,
                url=t.url,
                status=t.status,
                added_at=t.added_at,
            )
            for t in tracks
        ],
        history=[
            MusicSelectionOut(
                id=s.id,
                tg_message_id=s.tg_message_id,
                track_count=s.track_count,
                note=s.note,
                created_at=s.created_at,
            )
            for s in history
        ],
        week=week,
        top=[
            MusicTopTrackOut(
                id=t.id,
                title=t.title,
                performer=t.performer,
                url=t.url,
                likes=likes,
            )
            for t, likes in top_rows
        ],
    )


@router.post("/game/music/tracks/{track_id}/like", response_model=MusicLikeOut)
async def like_music_track(
    track_id: int, session: SessionDep, user: CurrentUser
) -> MusicLikeOut:
    """Поставить или снять лайк треку выпущенной подборки (Э17, задел H.8).

    Один роут на оба действия (toggle): мини-апп тапает по текущему состоянию и
    просто отображает ответ. Лайкнуть трек из пула нельзя — он ещё не в подборке,
    поэтому такой запрос под фичей-рубильником отдаём как 404.
    """
    from app.services.admin_config import get_game_music_enabled
    from app.services.game import music

    if not await is_game_enabled(session) or not await get_game_music_enabled(
        session
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="music off")

    result = await music.toggle_like(session, user_id=user.id, track_id=track_id)
    if result.status != music.LIKE_OK:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="track not published"
        )
    return MusicLikeOut(ok=True, liked=result.liked, likes=result.likes)


# --------------------------------------------------------------------------
# Э21: активности в мини-аппе — вопросы и голосовые, когда бот молчит в чате
#
# Зачем: в режимах «ачивки в приложение» / «всё в приложение» бот не пишет в
# чат, но механики должны продолжать работать. Поэтому лента становится
# «внутренней расширенной копией чата»: тут можно ответить на вопрос кнопкой или
# текстом, сдать/убрать голосовое и прослушать чужие варианты — не покидая апп.
# --------------------------------------------------------------------------


def _activity_options(answers: list[dict]) -> tuple[list[ActivityOptionOut], bool]:
    """Разобрать ответы промпта на кнопки и «нужен ли текст». Чистая функция.

    Кнопка-вариант — там, где у ответа есть человеческая `label` (Э21). Если
    хоть один ответ без подписи и не медиа — нужен свободный ввод. Если ни
    кнопок, ни текстового варианта не нашлось — всё равно даём ввод.
    """
    options: list[ActivityOptionOut] = []
    needs_text = False
    for ans in answers or []:
        label = str(ans.get("label") or "").strip()
        if label:
            options.append(
                ActivityOptionOut(label=label, xp=int(ans.get("xp") or 0))
            )
        elif not ans.get("media"):
            needs_text = True
    if not options and not needs_text:
        needs_text = True
    return options, needs_text


@router.get("/game/activities", response_model=ActivitiesOut)
async def activities_list(session: SessionDep, user: CurrentUser) -> ActivitiesOut:
    """Открытые вопросы (случайные события), на которые можно ответить в апп.

    Ответ засчитывается тем же путём, что и сообщение в чате
    (`events.try_answer`), поэтому «первый подходящий забирает XP» сохраняется.
    """
    if not await is_game_enabled(session):
        return ActivitiesOut(enabled=False, items=[])
    chat_id = get_settings().group_chat_id
    if not chat_id:
        return ActivitiesOut(enabled=True, items=[])
    now = datetime.now(timezone.utc)
    rows = (
        await session.scalars(
            select(GamePrompt)
            .where(
                GamePrompt.chat_id == chat_id,
                GamePrompt.closed_at.is_(None),
                GamePrompt.expires_at > now,
            )
            .order_by(GamePrompt.id.asc())
        )
    ).all()
    items: list[ActivityOut] = []
    for prompt in rows:
        options, needs_text = _activity_options(list(prompt.answers or []))
        items.append(
            ActivityOut(
                id=prompt.id,
                code=prompt.code,
                text=prompt.text,
                options=options,
                needs_text=needs_text,
                expires_at=prompt.expires_at,
                answered_by_me=prompt.winner_user_id == user.id,
            )
        )
    return ActivitiesOut(enabled=True, items=items)


@router.post(
    "/game/activities/{prompt_id}/answer", response_model=ActivityAnswerOut
)
async def activity_answer(
    prompt_id: int, body: ActivityAnswerIn, session: SessionDep, user: CurrentUser
) -> ActivityAnswerOut:
    """Ответить на вопрос из мини-аппа: кнопкой (label) или свободным текстом."""
    if not await is_game_enabled(session):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "game_disabled")
    chat_id = get_settings().group_chat_id
    if not chat_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "no_chat")
    won = await events.try_answer(
        session,
        chat_id=chat_id,
        telegram_id=user.telegram_id,
        text=body.text.strip(),
        prompt_id=prompt_id,
    )
    return ActivityAnswerOut(
        ok=won, status=("ok" if won else "no_match")
    )


@router.get("/game/voice/current", response_model=VoiceCurrentOut)
async def voice_current(session: SessionDep, user: CurrentUser) -> VoiceCurrentOut:
    """Текущее голосовое задание и сдачи — чтобы сдать/послушать прямо в ленте."""
    from app.services.admin_config import get_game_voice_enabled
    from app.services.game import voice
    from app.services.game.voice_catalog import TASKS_BY_CODE

    if not await is_game_enabled(session) or not await get_game_voice_enabled(session):
        return VoiceCurrentOut(enabled=False)
    now = datetime.now(timezone.utc)
    task = await session.scalar(
        select(GameVoiceTask)
        .where(
            GameVoiceTask.closed_at.is_(None),
            GameVoiceTask.expires_at > now,
        )
        .order_by(GameVoiceTask.id.desc())
        .limit(1)
    )
    if task is None:
        return VoiceCurrentOut(enabled=True)
    subs = await voice._submissions(session, task.id)
    names = await voice._user_names(session, [s.user_id for s in subs])
    catalog = TASKS_BY_CODE.get(task.code)
    mine = next((s for s in subs if s.user_id == user.id), None)
    return VoiceCurrentOut(
        enabled=True,
        task_id=task.id,
        title=catalog.title if catalog else task.code,
        text=task.text,
        reward=int(task.reward or 0),
        expires_at=task.expires_at,
        my_submission_id=mine.id if mine is not None else None,
        submissions=[
            VoiceSubmissionOut(
                id=s.id,
                user_id=s.user_id,
                user_name=names.get(s.user_id),
                duration=s.duration,
                submitted_at=s.submitted_at,
                is_mine=s.user_id == user.id,
            )
            for s in subs
        ],
    )


@router.post("/game/voice/submit", response_model=VoiceSubmitOut)
async def voice_submit_api(
    session: SessionDep,
    user: CurrentUser,
    file: UploadFile = File(...),
    duration: int | None = Form(default=None),
) -> VoiceSubmitOut:
    """Сдать голосовое из мини-аппа.

    Файл НЕ храним: пересылаем боту в личку участника, забираем `file_id` и
    отдаём его дальше по обычному пути (`voice.submit`). Если Telegram не принял
    — честно говорим «сдай в чате», а не глотаем ошибку.
    """
    from aiogram.types import BufferedInputFile

    from app.bot.dispatcher import get_bot
    from app.services.admin_config import get_game_voice_enabled
    from app.services.game import voice

    if not await is_game_enabled(session) or not await get_game_voice_enabled(session):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "voice off")
    data = await file.read()
    if not data or len(data) > _VOICE_MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad_audio")
    bot = get_bot()
    try:
        message = await bot.send_voice(
            chat_id=user.telegram_id,
            voice=BufferedInputFile(data, filename="voice.ogg"),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("game.voice_api_upload_failed", error=str(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "send_failed") from exc
    sent = getattr(message, "voice", None)
    if sent is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "send_failed")
    res = await voice.submit(
        session,
        telegram_id=user.telegram_id,
        file_id=sent.file_id,
        duration=duration if duration is not None else sent.duration,
        tg_message_id=message.message_id,
        at=datetime.now(timezone.utc),
    )
    return VoiceSubmitOut(ok=res.ok, status=res.status, reward=res.reward)


@router.delete("/game/voice/submission", response_model=VoiceSubmitOut)
async def voice_withdraw_api(session: SessionDep, user: CurrentUser) -> VoiceSubmitOut:
    """Убрать свой голосовой вариант (пока задание открыто).

    Пишем «могилку» (`voice.record_withdrawal`), поэтому повторная сдача не даст
    второй XP за то же задание. Опыт не отзываем — это осознанно: откат начислений
    сложнее, чем цена случайного «убрал-и-передумал» на шестерых.
    """
    from app.services.game import voice

    now = datetime.now(timezone.utc)
    task = await session.scalar(
        select(GameVoiceTask)
        .where(
            GameVoiceTask.closed_at.is_(None),
            GameVoiceTask.expires_at > now,
        )
        .order_by(GameVoiceTask.id.desc())
        .limit(1)
    )
    if task is None:
        return VoiceSubmitOut(ok=False, status="no_task")
    sub = await session.scalar(
        select(GameVoiceSubmission).where(
            GameVoiceSubmission.task_id == task.id,
            GameVoiceSubmission.user_id == user.id,
        )
    )
    if sub is None:
        return VoiceSubmitOut(ok=False, status="nothing")
    await session.delete(sub)
    voice.record_withdrawal(session, task_id=task.id, user_id=user.id)
    await session.commit()
    return VoiceSubmitOut(ok=True, status="withdrawn")


@router.get("/game/voice/submissions/{submission_id}/audio")
async def voice_audio(
    submission_id: int, session: SessionDep, _: CurrentUser
) -> Response:
    """Прослушать чужой (или свой) вариант прямо в ленте.

    Проксируем: файла у нас нет, берём его у Telegram по `file_id` и стримим
    клиенту. Ничего не храним — важно для слабого хоста.
    """
    from app.bot.dispatcher import get_bot

    sub = await session.get(GameVoiceSubmission, submission_id)
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "submission_not_found")
    bot = get_bot()
    try:
        tg_file = await bot.get_file(sub.file_id)
        if tg_file is None or not tg_file.file_path:
            raise RuntimeError("no file_path")
        buf = await bot.download_file(tg_file.file_path)
        data = buf.read()
    except Exception as exc:  # noqa: BLE001
        log.warning("game.voice_audio_failed", error=str(exc))
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "audio_unavailable"
        ) from exc
    return Response(content=data, media_type="audio/ogg")


@router.post("/game/music/tracks", response_model=MusicAddOut)
async def music_add_track(
    body: MusicAddIn, session: SessionDep, user: CurrentUser
) -> MusicAddOut:
    """Э21: сдать трек ссылкой прямо в приложении (аудиофайл — по-прежнему боту).

    Аудио из мини-аппа пока не принимаем: как и голосовые, это требует двойного
    хопа через Telegram. Ссылки покрывают основной сценарий («вот трек»).
    """
    from app.services.admin_config import get_game_music_enabled
    from app.services.game import music

    if not await is_game_enabled(session) or not await get_game_music_enabled(session):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "music off")
    res = await music.add_track(
        session,
        telegram_id=user.telegram_id,
        kind="link",
        url=body.url,
        title=body.title,
        performer=body.performer,
    )
    return MusicAddOut(
        ok=res.status == music.OK, status=res.status, week_count=res.week_count
    )
