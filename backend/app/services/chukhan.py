"""Чухан недели: каждый понедельник 12:00 МСК выбирается случайный участник
шестёрки с весами из конфига и публикуется в групповой чат.

Идемпотентно по `week_start` (UTC, понедельник 00:00) — повторный запуск
в ту же неделю не создаёт второй пост."""
from __future__ import annotations

import asyncio
import os
import random
from datetime import datetime, time, timedelta, timezone

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import URLInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import User, WeeklyChukhan
from app.services.admin_config import get_chukhan_reasons, get_chukhan_weights
from app.services.avatars import sync_user_avatar
from app.services.phrase_weights import (
    CHUKHAN_USE_COUNTS_KEY,
    get_use_counts,
    increment_use_count,
    weighted_choice,
)

log = structlog.get_logger()


# GHG7 P11: таймаут отправки чухан-поста. Раньше обёртки не было вовсе — send
# полагался только на 30с-таймаут сессии бота (`_IPv4AiohttpSession`), и при
# throttling канала (РКН, TG отвечает 8–30с) основной пост мог «зависнуть»
# дольше барабанной дроби и отвалиться, оставив в чате огрызок drumroll'а
# (прод-инцидент 03.06). Переиспользуем общий env `LOSER_SEND_TIMEOUT`
# (дефолт 25с < 30с сессии) — зеркало `routes_meetings._loser_send_timeout`.
def _chukhan_send_timeout() -> float:
    raw = os.getenv("LOSER_SEND_TIMEOUT")
    if raw is None:
        return 25.0
    try:
        return float(int(raw))
    except ValueError:
        return 25.0


def current_week_start(now: datetime | None = None) -> datetime:
    """Понедельник 00:00 UTC на неделю, в которую попадает `now`."""
    n = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    monday = (n - timedelta(days=n.weekday())).date()
    return datetime.combine(monday, time.min, tzinfo=timezone.utc)


def _pick_weighted(users: list[User], weight_map: dict[int, float]) -> User:
    weights = [max(0.0, weight_map.get(u.telegram_id, 1.0)) for u in users]
    if sum(weights) <= 0:
        weights = [1.0] * len(users)
    return random.choices(users, weights=weights, k=1)[0]


async def pick_chukhan_for_week(
    session: AsyncSession,
    *,
    week_start: datetime | None = None,
) -> tuple[WeeklyChukhan, User, bool]:
    """Возвращает (роу, пользователь, created): created=False если на эту неделю
    чухан уже был назначен.

    Внимание: при created=True вызывающий код обязан либо commit'нуть session
    после успешной публикации, либо rollback'нуть, если в TG ничего не ушло.
    Этот метод намеренно не коммитит — атомарность гарантирует announce_chukhan.
    """
    ws = week_start or current_week_start()
    existing = await session.scalar(
        select(WeeklyChukhan).where(WeeklyChukhan.week_start == ws)
    )
    if existing is not None:
        user = await session.get(User, existing.user_id)
        assert user is not None
        return existing, user, False

    users = list((await session.scalars(select(User))).all())
    if not users:
        raise RuntimeError("no users to pick from")

    weights = await get_chukhan_weights(session)
    chosen = _pick_weighted(users, weights)
    snapshot = {
        str(u.telegram_id): weights.get(u.telegram_id, 1.0) for u in users
    }
    row = WeeklyChukhan(
        week_start=ws,
        user_id=chosen.id,
        weights_snapshot=snapshot,
    )
    session.add(row)
    await session.flush()
    return row, chosen, True


CHUKHAN_TAGLINES = [
    "Поздравляем, носи гордо 🐓",
    "Неделя твоя, чухан. Не забудь занести.",
    "Готовь очко, чухан. Неделя будет длинная.",
    "Ты сегодня выиграл главный приз — звание чухана. Носи с гордостью",
    "Чухан недели выявлен. Остальные могут выдохнуть.",
    "Веник, тапки и табуретка — твой новый трон.",
    "Будешь главным по шконке",
    "Чухан недели активирован. Остальным - принять ожидающую позу",
    "В ассортименте чуханов, ты - премиум уровень.",
    "Система не ошибается.",
    "Неделя твоя. Пользуйся моментом, пока остальные в тени.",
    "По версии жюри ты — самый сочный фрукт в этом огороде.",
    "Ты не искал этого звания, но оно нашло тебя. Классика.",
    "В чуханской иерархии ты сегодня поднялся на самый верх.",
    "Прими титул. Он тебе к лицу.",
    "Веник в углу, ведро у двери — звание подтверждено.",
    "Кто рано встал — тот и чухан. Расписание не врёт.",
    "Аватарка одобрена комиссией. Поздравляем 🤝",
    "за немытую кружку на столе",
    "за рассказ про крипту в нерабочее время",
    "за мутные движения на общаке",
    "По совокупности косяков за неделю",
    "замечен на скользяке",
    "по решению дворового сходняка",
    "не прошел проверку стулом",
    "не удержал масть",
    "по утрате доверия",
    "шнырял у параши с бывалым видом",
    "за водолазные наклонности",
    "По решению барака",
    "не удержал черенок судьбы",
    "метит на чужой шконарь",
    "братва решила: ближе к ведру",
    "решал вопросики на коленях",
    "Сдал анализы - сплошной белок. Чухан недели, брат.",
    "Пока все в общак кидали - ты кидал в другом месте",
    "Не пояснил за модный стикер пак",
    "Пестро зашел в хату",
    "Срал в школьном сортире",
    "Был в прайме - Носил джинсы с рваными коленками",
    "За систематическое пополнение фонда черкашей",
    "Приторговывание тузом… ниже курса"
    "держит ёршик увереннее чем бутылку пива",
    "за серийное производство хуевых решений",
    "контактировал с хуйней",
    "Последним вышел из автозака",
    "В остальные номинации не прошёл по ширине",
    "Мастеровито поедал бананы",
    "Слишком часто поглядывает на чайник",
    "по итогам проверки оказался вторником",
    "за контрабанду плохих предчувствий",
    "За непочтительное отношение к картофелю",
    "Слишком похож на Виталика",
    "Зарегистрирован в списке природных катаклизмов",
    "использовал дверной проём не по назначению",
    "Живет между гранью закона и майонеза",
    "Шелестит не по сезону",
    "Забыл вкус отцовской спермы",
    "Блатной шляпы нанюхался",
    "Оплачивает яндекс плюс",
    "не смог пояснить за Великий Устюг",
    "Выглядел виноватым",
    "Сегодня он, завтра тоже он",
    "Провел на параше столько времени, что выучил состав освежителя на казахском",
]

def _format_announcement(user: User, *, reason: str | None = None) -> str:
    name = user.display_name
    handle = f"@{user.username}" if user.username else name
    # GHG6 AD6: если админ настроил chukhan_reasons — берём из них; иначе
    # старые CHUKHAN_TAGLINES. Аргумент `reason` пробрасывается извне (см.
    # announce_chukhan), чтобы тест/UI могли проверить, какая фраза выбрана.
    tagline = reason or random.choice(CHUKHAN_TAGLINES)
    return (
        "💩💩💩 <b>ЧУХАН НЕДЕЛИ</b> 💩💩💩\n"
        "🤮🤢🤮🤢🤮🤢🤮🤢🤮\n\n"
        f"На этой неделе чуханом назначен:\n"
        f"👉 <b>{name}</b> ({handle}) 👈\n\n"
        "🪰💨🪰💨🪰💨🪰💨🪰\n"
        f"<i>{tagline}</i>"
    )


async def _drumroll(bot: Bot, chat_id: int, name: str) -> int | None:
    """Серия edit'ов одного сообщения для эффекта барабанной дроби.

    Шаги: 💩 → 💩💩💩 → 🥁🥁🥁 → имя. Между шагами 0.6с (Telegram rate-limit
    edit_message ≈ 1/с на чат, держим запас).

    GHG7 P11: возвращает message_id своего сообщения (или None, если даже
    первый кадр не ушёл). Вызывающий код использует id, чтобы удалить огрызок
    дроби, если основной пост не доставится (иначе в чате висит «🎉 Имя 🎉» без
    самого поста — прод-инцидент 03.06)."""
    frames = [
        "💩  …  💩",
        "💩💩  …  💩💩",
        "🥁🥁🥁 <b>чухан недели…</b> 🥁🥁🥁",
        f"🎉 <b>{name}</b> 🎉",
    ]
    try:
        msg = await bot.send_message(chat_id=chat_id, text=frames[0])
    except TelegramAPIError as exc:
        log.warning("chukhan.drumroll_start_failed", error=str(exc))
        return None
    for frame in frames[1:]:
        await asyncio.sleep(0.6)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg.message_id, text=frame
            )
        except TelegramAPIError as exc:
            log.warning("chukhan.drumroll_frame_failed", error=str(exc))
            break
    return msg.message_id


async def announce_chukhan(bot: Bot, session: AsyncSession) -> WeeklyChukhan | None:
    settings = get_settings()
    if not settings.group_chat_id:
        log.info("chukhan.skip_no_group_chat")
        return None

    row, user, created = await pick_chukhan_for_week(session)
    if not created and row.posted_at is not None:
        log.info("chukhan.already_posted", week_start=row.week_start.isoformat())
        return row

    # Подтянуть актуальную аватарку перед публикацией.
    try:
        await sync_user_avatar(session, bot, user)
    except Exception:  # noqa: BLE001
        log.warning("chukhan.avatar_sync_failed", user_id=user.id)

    # GHG6 AD6: подтянем кастомные фразы чухана из admin_config (если заданы).
    try:
        custom_reasons = await get_chukhan_reasons(session)
    except Exception:  # noqa: BLE001
        custom_reasons = []
    # GHG6 E5: взвешенный выбор по use_count для кастомных фраз. Для дефолтных
    # CHUKHAN_TAGLINES счётчики не ведём — фолбэк остаётся равномерным.
    reason = None
    if custom_reasons:
        use_counts = await get_use_counts(session, CHUKHAN_USE_COUNTS_KEY)
        reason = weighted_choice(custom_reasons, use_counts) or random.choice(custom_reasons)
        await increment_use_count(session, CHUKHAN_USE_COUNTS_KEY, reason)
    text = _format_announcement(user, reason=reason)
    # «Барабанная дробь» — best-effort, не блокирует основной пост. Запоминаем
    # message_id дроби, чтобы удалить огрызок, если основной пост не доедет
    # (GHG7 P11, прод-инцидент 03.06: в чате остался висеть «🎉 Имя 🎉» без поста).
    drumroll_msg_id: int | None = None
    try:
        drumroll_msg_id = await _drumroll(bot, settings.group_chat_id, user.display_name)
    except TelegramAPIError as exc:
        log.warning("chukhan.drumroll_failed", error=str(exc))

    send_timeout = _chukhan_send_timeout()
    # Основной пост. Send'ы обёрнуты в asyncio.wait_for(send_timeout) — GHG7 P11.
    msg = None
    try:
        if user.avatar_url:
            try:
                msg = await asyncio.wait_for(
                    bot.send_photo(
                        chat_id=settings.group_chat_id,
                        photo=URLInputFile(user.avatar_url),
                        caption=text,
                        disable_notification=False,
                    ),
                    timeout=send_timeout,
                )
            except (TelegramAPIError, asyncio.TimeoutError) as exc:
                # Фото не ушло — пробуем текстовый фолбэк ниже.
                log.warning("chukhan.send_photo_failed", error=str(exc))
        if msg is None:
            msg = await asyncio.wait_for(
                bot.send_message(
                    chat_id=settings.group_chat_id,
                    text=text,
                    disable_notification=False,
                ),
                timeout=send_timeout,
            )
    except Exception as exc:  # noqa: BLE001
        # GHG7 P11: пост не доехал. (1) чистим огрызок барабанной дроби, чтобы в
        # чате не висел «🎉 Имя 🎉» без поста. (2) НЕ откатываем пик — фиксируем
        # строку как недоставленную (posted_at остаётся None). Календарь/титул её
        # не покажут (фильтр posted_at IS NOT NULL в routes_calendar), а ретрай
        # (retry_undelivered_chukhan / следующий триггер) найдёт ту же строку и
        # добьёт доставку тем же юзером — не выбирая нового чухана.
        log.warning("chukhan.send_failed_pick_kept", error=str(exc))
        if drumroll_msg_id is not None:
            try:
                await bot.delete_message(
                    chat_id=settings.group_chat_id, message_id=drumroll_msg_id
                )
            except TelegramAPIError as del_exc:
                log.warning("chukhan.drumroll_cleanup_failed", error=str(del_exc))
        await session.commit()
        return None

    row.posted_at = datetime.now(timezone.utc)
    row.tg_message_id = msg.message_id
    await session.commit()
    log.info(
        "chukhan.posted",
        week_start=row.week_start.isoformat(),
        user=user.display_name,
    )

    # Опрос-обжалование — best-effort, не критично для атомарности.
    try:
        await bot.send_poll(
            chat_id=settings.group_chat_id,
            question=f"Согласны с тем, что {user.display_name} — чухан недели?",
            options=["✅ Согласны", "🙅 Обжаловать"],
            is_anonymous=False,
            allows_multiple_answers=False,
            open_period=3600,
            reply_to_message_id=msg.message_id,
        )
    except TelegramAPIError as exc:
        log.warning("chukhan.appeal_poll_failed", error=str(exc))
    return row


async def run_chukhan_job(bot: Bot) -> None:
    """Точка входа для APScheduler — открывает свою сессию."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            await announce_chukhan(bot, session)
        except Exception:  # noqa: BLE001
            log.exception("chukhan.job_failed")


async def retry_undelivered_chukhan(bot: Bot) -> bool:
    """GHG7 P11: дотянуть недоставленного чухана ТЕКУЩЕЙ недели.

    Лечит инцидент №1 (03.06): cron-ролл понедельника мог упасть в окно
    недоступности канала/Neon и не повториться до след. недели. После P11.1 такой
    пик не теряется — строка `WeeklyChukhan` остаётся с `posted_at IS NULL`. Эта
    функция ищет её и зовёт `announce_chukhan`, который добьёт доставку тем же
    юзером (идемпотентность `pick_chukhan_for_week` по `week_start`).

    Дёшево для Neon: в обычном случае один SELECT, который ничего не находит.
    Возвращает True, если доставка прошла в этом вызове, иначе False.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        ws = current_week_start()
        pending = await session.scalar(
            select(WeeklyChukhan).where(
                WeeklyChukhan.week_start == ws,
                WeeklyChukhan.posted_at.is_(None),
            )
        )
        if pending is None:
            return False
        log.info("chukhan.retry_undelivered", week_start=ws.isoformat())
        try:
            row = await announce_chukhan(bot, session)
        except Exception:  # noqa: BLE001
            log.exception("chukhan.retry_failed")
            return False
        return row is not None and row.posted_at is not None
