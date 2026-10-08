from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.config import get_settings
from app.db.models import GameProfile, User
from app.schemas.user import UserOut
from app.services.admin_config import (
    get_ui_hide_greeting,
    get_ui_muted_feed,
    get_ui_show_last_seen,
    get_ui_welcome_format,
    set_ui_hide_greeting,
    set_ui_muted_feed,
    set_ui_show_last_seen,
    set_ui_welcome_format,
)

router = APIRouter(tags=["users"])


def _avatar_display_url(u: User) -> str | None:
    """URL аватарки для ОТОБРАЖЕНИЯ в мини-аппе (НЕ для чухан-постинга).

    Приоритет: ручная ссылка (Серж/Митян — приватность TG) → стабильный прокси
    /api/avatar/{id} → None (фронт рисует инициалы). Прямой `u.avatar_url` сюда
    НЕ отдаём: его file_path протухает за ~1ч → «приложуха забывает аватарки»
    (прод-фидбек 18.06 #2). Прокси-URL резолвит свежий file_path по стабильному
    file_id на лету. `?v=` — cache-buster: меняется вместе с file_id (т.е. когда
    юзер реально сменил аватар), иначе браузер показывал бы старую картинку по
    неизменному URL.
    """
    if u.avatar_manual_url:
        return u.avatar_manual_url
    if u.avatar_file_id:
        base = get_settings().public_base_url.rstrip("/")
        ver = u.avatar_file_id[-12:]
        return f"{base}/api/avatar/{u.id}?v={ver}"
    return None


def _to_out(
    u: User, *, admin_ids: set[int], custom_name: str | None = None
) -> UserOut:
    """`custom_name` (GHG10 Э8.7) перекрывает TG-имя ВНУТРИ мини-аппа.

    Передаётся из `game_profiles.custom_name` вызывающим кодом (батчем для
    списка, точечно для `/me`) — сам `_to_out` в БД не ходит, чтобы не появилось
    N+1 на списке участников.
    """
    return UserOut(
        id=u.id,
        telegram_id=u.telegram_id,
        display_name=custom_name or u.display_name,
        username=u.username,
        avatar_url=_avatar_display_url(u),
        color_hex=u.color_hex,
        timezone=u.timezone,
        created_at=u.created_at,
        is_admin=u.telegram_id in admin_ids,
    )


@router.get("/me", response_model=UserOut)
async def me(session: SessionDep, user: CurrentUser) -> UserOut:
    # GHG11(10): мини-апп при запуске зовёт `/me` — здесь и отмечаем «последний
    # заход». Best-effort и троттлинг внутри (см. services/game/presence).
    from app.services.game import presence

    await presence.touch_last_app_seen(session, user.id)
    admin_ids = get_settings().admin_tg_id_set
    custom_name = await session.scalar(
        select(GameProfile.custom_name).where(GameProfile.user_id == user.id)
    )
    return _to_out(user, admin_ids=admin_ids, custom_name=custom_name)


@router.get("/users", response_model=list[UserOut])
async def list_users(session: SessionDep, _: CurrentUser) -> list[UserOut]:
    admin_ids = get_settings().admin_tg_id_set
    result = await session.scalars(select(User).order_by(User.id))
    # Одно доп. чтение на весь список (не N+1): кастомные имена из игровых профилей.
    custom_names = {
        int(uid): name
        for uid, name in (
            await session.execute(
                select(GameProfile.user_id, GameProfile.custom_name).where(
                    GameProfile.custom_name.is_not(None)
                )
            )
        ).all()
    }
    return [
        _to_out(u, admin_ids=admin_ids, custom_name=custom_names.get(u.id))
        for u in result.all()
    ]


# --- GHG8 (18.06 #2): прокси аватарок ---
# Стабильный URL для <img> в мини-аппе. ПУБЛИЧНЫЙ (без tma-auth): тег <img> не
# умеет слать Authorization-заголовок. Утечки нет — отдаём только публичную
# аватарку по числовому id, токен бота наружу не идёт (проксируем байты сами,
# не редиректим на file-URL с токеном). file_path резолвится по стабильному
# file_id и кешируется в памяти (≤ раз в 50 мин на участника) — узкий канал к TG
# почти не трогаем. Чинит «приложуха забывает аватарки» (раньше в БД хранился
# протухающий за ~1ч file-URL).
@router.get("/avatar/{user_id}")
async def avatar_proxy(user_id: int, session: SessionDep, response: Response):
    from app.bot.dispatcher import get_bot
    from app.services.avatars import fetch_avatar_bytes

    u = await session.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    # Ручная ссылка обслуживается напрямую фронтом (она и так стабильна) —
    # сюда участник с ручной картинкой и без TG-фото попасть не должен, но на
    # всякий случай отвечаем 404, чтобы не маскировать ошибку конфигурации.
    if not u.avatar_file_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no_avatar")

    data = await fetch_avatar_bytes(get_bot(), u.avatar_file_id)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "avatar_unavailable")
    payload, content_type = data
    response.headers["Content-Type"] = content_type
    # Кешируем на сутки; смена аватара меняет file_id → меняется ?v= в URL →
    # браузер запросит заново (cache-bust на стороне URL, см. _avatar_display_url).
    response.headers["Cache-Control"] = "public, max-age=86400"
    return Response(
        content=payload,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# --- E7: per-user UI prefs (закрываемое приветствие) ---
# GHG8 P4: + welcome_format (name|avatar|both, P4.1.b — один селектор на все
# welcome-блоки). В PUT оба поля опциональны — клиенты шлют только то, что
# меняют (старый фронт слал {hide_greeting} без формата — совместимо).


class UiPrefsOut(BaseModel):
    hide_greeting: bool
    welcome_format: str  # name | avatar | both
    # GHG11(7): кого скрыть в ленте (внутренние id) — своя галочка неснимаемая.
    muted_feed: list[int] = []
    # GHG11(10): показывать ли другим мой последний заход в мини-апп (дефолт — да).
    show_last_seen: bool = True


class NotificationOut(BaseModel):
    """Уведомление в колокольчике (GHG11(9)).

    `track_id` вытаскиваем из `payload` — фронту его хватает, чтобы отвести к
    треку; сам `payload` наружу не отдаём (внутренний формат).
    """

    id: int
    kind: str
    text: str
    track_id: int | None = None
    created_at: datetime | None = None
    read: bool = False


class NotificationsOut(BaseModel):
    items: list[NotificationOut] = []
    unread: int = 0


class NotificationsReadIn(BaseModel):
    """Отметить прочитанными: список id или всё сразу (`all=true`)."""

    ids: list[int] | None = None
    all: bool = False


class UiPrefsPatch(BaseModel):
    hide_greeting: bool | None = None
    welcome_format: str | None = Field(
        None, pattern="^(name|avatar|both)$"
    )
    muted_feed: list[int] | None = None
    show_last_seen: bool | None = None


@router.get("/me/ui-prefs", response_model=UiPrefsOut)
async def get_ui_prefs(session: SessionDep, user: CurrentUser) -> UiPrefsOut:
    return UiPrefsOut(
        hide_greeting=await get_ui_hide_greeting(session, user.telegram_id),
        welcome_format=await get_ui_welcome_format(session, user.telegram_id),
        muted_feed=sorted(await get_ui_muted_feed(session, user.telegram_id)),
        show_last_seen=await get_ui_show_last_seen(session, user.telegram_id),
    )


async def _notifications_out(session: SessionDep, user_id: int) -> NotificationsOut:
    """Уведомления + счётчик непрочитанных — общее для GET и POST."""
    from app.services import notifications

    rows = await notifications.list_for_user(session, user_id)
    return NotificationsOut(
        items=[
            NotificationOut(
                id=row.id,
                kind=row.kind,
                text=row.text,
                track_id=_payload_track_id(row.payload),
                created_at=row.created_at,
                read=row.read_at is not None,
            )
            for row in rows
        ],
        unread=await notifications.unread_count(session, user_id),
    )


def _payload_track_id(payload: object) -> int | None:
    """`track_id` из payload уведомления — с защитой от мусора в JSONB."""
    if not isinstance(payload, dict):
        return None
    value = payload.get("track_id")
    return int(value) if isinstance(value, int) else None


@router.get("/me/notifications", response_model=NotificationsOut)
async def my_notifications(session: SessionDep, user: CurrentUser) -> NotificationsOut:
    """Личные уведомления (пока — лайки своих треков) и счётчик непрочитанных.

    Своё, не общее: в чат такие события не ходят, поэтому и в ленте их нет —
    они ждут здесь, в колокольчике.
    """
    return await _notifications_out(session, user.id)


@router.post("/me/notifications/read", response_model=NotificationsOut)
async def read_notifications(
    body: NotificationsReadIn, session: SessionDep, user: CurrentUser
) -> NotificationsOut:
    """Отметить прочитанными (`ids` или всё сразу) и вернуть новый список.

    Возвращаем состояние целиком, а не только «ok»: фронту сразу нужен новый
    счётчик для бейджа, а лишний рефетч — лишний запрос к базе.
    """
    from app.services import notifications

    await notifications.mark_read(session, user.id, ids=body.ids, all_=body.all)
    return await _notifications_out(session, user.id)


@router.put("/me/ui-prefs", response_model=UiPrefsOut)
async def put_ui_prefs(
    body: UiPrefsPatch, session: SessionDep, user: CurrentUser
) -> UiPrefsOut:
    if body.hide_greeting is not None:
        await set_ui_hide_greeting(session, user.telegram_id, body.hide_greeting)
    if body.welcome_format is not None:
        await set_ui_welcome_format(
            session, user.telegram_id, body.welcome_format
        )
    if body.muted_feed is not None:
        # Себя из списка выкидываем: свою ленту ломать нельзя (их галочка
        # неснимаемая на фронте, но сервер тоже защищается от кривого клиента).
        await set_ui_muted_feed(
            session,
            user.telegram_id,
            {i for i in body.muted_feed if i != user.id},
        )
    if body.show_last_seen is not None:
        await set_ui_show_last_seen(session, user.telegram_id, body.show_last_seen)
    return UiPrefsOut(
        hide_greeting=await get_ui_hide_greeting(session, user.telegram_id),
        welcome_format=await get_ui_welcome_format(session, user.telegram_id),
        muted_feed=sorted(await get_ui_muted_feed(session, user.telegram_id)),
        show_last_seen=await get_ui_show_last_seen(session, user.telegram_id),
    )
