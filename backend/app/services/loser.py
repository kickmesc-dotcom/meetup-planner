from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LoserRoll, User, WormAssignment
from app.services.admin_config import (
    get_loser_reasons,
    get_worm_chance,
    is_worm_enabled,
)
from app.services.phrase_weights import (
    LOSER_USE_COUNTS_KEY,
    get_use_counts,
    increment_use_count,
    weighted_choice,
)


WORM_REASON_TEXT = "Особая номинация: Червь-пидор"


@dataclass
class WormEvent:
    """Дополнительная информация о выпадении «червя-пидора» при roll_loser.

    Передаётся в `on_announce` как третий позиционный аргумент. Если червь
    не выпал — `triggered=False`, остальные поля игнорируются.
    """
    triggered: bool = False
    prev_worm_name: str | None = None  # display_name предыдущего червя, если был
    chance_used: float = 0.0
    # T3.6 (г): расширение анонса «что даёт звание господина». Заполняется в
    # roll_loser ТОЛЬКО если включён режим worm_master (иначе None → анонс как
    # раньше). Готовый многострочный блок (БД из форматтера не дёргаем).
    announce_extra: str | None = None


@dataclass
class MasterSycophancy:
    """T3.6 (а): подхалимское обрамление обычного анонса лоха, когда «жертва»
    сама является ТЕКУЩИМ червём-господином. prefix/suffix уже с подставленным
    именем (рендерятся в roll_loser). Любое из полей может быть None."""
    prefix: str | None = None
    suffix: str | None = None


@dataclass
class RollExtras:
    """Контейнер «лишних» сведений о ролле для `on_announce`. Расширяемый —
    в будущем сюда могут попасть, например, «лох недели/месяца»-хайлайты.

    GHG8 P3: `immunity_skipped` — display_name именинников, выпадавших до
    финального лоха (announce-режим иммунитета). Вызывающий код оглашает их
    («мог бы стать…, но ДР») с задержкой ПЕРЕД основным постом. В БД эти
    «черновые» попытки не пишутся — row создаётся только для финального."""
    worm: WormEvent = field(default_factory=WormEvent)
    immunity_skipped: list[str] = field(default_factory=list)
    # T3.6 (а): заполняется, только если лох == текущий червь-господин и режим
    # worm_master включён. None → обычный анонс без подхалимажа.
    worm_master: MasterSycophancy | None = None

COOLDOWN = timedelta(hours=12)

LOSER_REASONS = [
"слился с последней встречи",
"откисает с левыми типами",
"воняет говной",
"всплывает только когда ему что-то надо",
"опять не выпил таблетки",
"забыл дорогу в конфу",
"дает заднюю даже если ни о чем не договаривался",
"пришёл, увидел, обосрался",
"ссыт мужицкого движняка",
"по жизни сел не на тот кирпич",
"потерялся между диваном и кухней",
"его юмор умер в 2007",
"Был замечен с женщиной",
"Слишком уверенно молчит",
"С тоской моргет в сторону Самары",
"вступил в конфликт с понятием 'ладно'... и проиграл",
"опять включил режим призрака",
"сидит на морозе как неродной",
"воюет не в ту сторону",
"давно не трогал траву",
"слишком нестабилен даже для мемов",
"Пердит химозой",
"Забыл, почем петрушка в магадане",
"Вечная: ебучка на беззвучке",
"Не шурши, пакетик",
"Хотел почуять запах моря - нассал себе на спину",
"Адепт банки принглс и перчатки",
"Такой молодой, а уже пытается клитором командовать",
"Когда его посылают - добирается без пробок",
"Инвестировал молодость в robux’ы",
"Тайно мечтает стать ледибоем",
"Добился успеха в тиктоке",
"Зарабатывает на жизнь паркуром",
"Не смотрел день студента",
"Ты волыну то спрячь, сталкер",
"Парень с виду неплохой, только ссытся и глухой",
"Уснул на вписке",
"Засимпил дота-стримершу",
"Берет авик на эко-раундах",
"Нафидил в гулаге",
"Гелем вымазан, откуда вылез он?",
"Меняет трусы после первого черкаша",
"Не пробовал чувашское пиво",
"Срет не снимая футболку",
"Отсиделся в штабе писарем",
"Одно слово - Румын",
"Не проходил «мафию»",
"Грезит днем, когда в моду вернутся узкачи",
"Обиделся на алгоритм",
"По любому рассказывал в школе истории про то, как поебался в деревне",
"Если обижается — идет снимать поставленные лайки",
"Любитель поиграть на саппорте",
"Успешно подрочил на выпуск «голые и смешные»",
"опять обещал и опять нихуя",
"как обычно - косплеит окуня",
"опять наступил на собственный хуй",
"выглядит как человек с тремя кредитами",
"пытается быть сигмой после 30",
"его аура требуется капремонт",
"за срыв поставки годноты",
"родился во вторую смену",
"Просто посмотри на него",
"Да потому что... блять... вообще блять! УУУ!!!",
"da ty ohuel chtole",
"Общается голосовухами",
"присоединяется только когда все уже накидались",
"слился, потому что 'устал'",
"ставит лайки на свои же посты",
"ролплеит скуфа, а сам без пуза",
"перешел на безалкогольное и НЕ ЖАЛЕЕТ",
"переоценил уровень народной любви",
"не смог пройти мимо собственной хуйни",
"имеет вопросы к жизни, но жизнь не отвечает",
"забыл согласовать с руководством своё существование",
"замечен в состоянии полной бесполезности",
"записался в легенды, попал в статистику",
"выглядит как побочный квест",
"Что-то в нём есть. Иногда это даже мешает сидеть",
"Стремится заполнить внутреннюю пустоту... жрет желтый снег",
"проживает свою худшую арку",
"является конечным продуктом распада девяностых",
"потерял берега ещё в апреле",
"родился зря, но смешно",
]


async def time_until_next_roll(
    session: AsyncSession, *, source: str = "manual"
) -> timedelta:
    """GHG6 H1: cooldown считается раздельно по семейству источников.

    Раньше функция смотрела МАКС rolled_at по всей таблице — авто-лох,
    срабатывая каждый день, блокировал ручную рулетку. Теперь callers
    передают `source` (обычно 'manual' для UI-кнопок), и в окне cooldown'а
    учитываются только строки этого же семейства.

    `source='auto'` для полноты симметрии (если когда-нибудь авто-задаче
    понадобится «не дёргать дважды подряд за час»), но scheduler-job сейчас
    передаёт `bypass_cooldown=True` в `roll_loser` и эту функцию не зовёт.
    """
    last = await session.scalar(
        select(func.max(LoserRoll.rolled_at)).where(LoserRoll.source == source)
    )
    if last is None:
        return timedelta(0)
    elapsed = datetime.now(timezone.utc) - last
    remaining = COOLDOWN - elapsed
    return max(timedelta(0), remaining)


AnnounceFn = Callable[..., Awaitable[None]]


async def roll_loser(
    session: AsyncSession,
    *,
    rolled_by: User,
    on_announce: AnnounceFn | None = None,
    source: str = "manual",
    bypass_cooldown: bool = False,
) -> LoserRoll:
    """Roll a loser atomically with the chat announcement.

    If `on_announce` is provided, it's invoked AFTER flushing the row but
    BEFORE commit. If it raises, the transaction is rolled back so the
    roll can be retried — no «phantom» DB row without a TG message.

    E8 (GHG6): с шансом `admin_config["worm.chance"]` (default 0.01) выпадает
    «червь-пидор». В этом случае `LoserRoll.reason_text` = `WORM_REASON_TEXT`
    (не случайная фраза из пула), плюс атомарно обновляется таблица
    `worm_assignments`: предыдущая активная запись получает `ended_at=now()`,
    создаётся новая для выбранного юзера. Сигнатура `on_announce` расширена:
    третий аргумент — `RollExtras` с `worm: WormEvent`. Callers, которые
    игнорируют третий аргумент, должны принять `*_` — иначе TypeError на raise.

    GHG6 H1: `source` пишется в `LoserRoll.source` ('auto' для autoloser-job,
    'manual' для UI/chat-команды/admin force-reroll). `bypass_cooldown=True`
    скипает проверку — для admin force-reroll и для autoloser-job, которые
    не должны блокировать друг друга. Cooldown между двумя ручными рулетками
    подряд остаётся в силе.
    """
    if not bypass_cooldown:
        remaining = await time_until_next_roll(session, source=source)
        if remaining > timedelta(0):
            raise CooldownError(remaining)

    users = list((await session.scalars(select(User))).all())
    if not users:
        raise RuntimeError("no users in DB")

    # GHG8 P3: иммунитет именинника. silent — исключаем из пула; announce —
    # имена «черновых» именинников уезжают в extras.immunity_skipped, в БД
    # попадает только финальный (не-именинник).
    from app.services.birthday_immunity import immune_pick

    pick = await immune_pick(session, users, random.choice)
    loser = pick.user

    # E8: бросаем «червь-пидор»
    worm_enabled = await is_worm_enabled(session)
    worm_chance = await get_worm_chance(session) if worm_enabled else 0.0
    is_worm = decide_worm(
        enabled=worm_enabled, chance=worm_chance, rng_value=random.random()
    )

    if is_worm:
        reason = WORM_REASON_TEXT
    else:
        # Берём актуальный список из admin_config (с фолбэком на in-code LOSER_REASONS).
        reasons = await get_loser_reasons(session)
        pool = reasons or list(LOSER_REASONS)
        # GHG6 E5: взвешенный выбор — вес 1/(1+use_count). Свежие фразы чаще,
        # но «нулевого приоритета» нет: уже-использованные всё равно могут
        # выпасть, просто реже.
        use_counts = await get_use_counts(session, LOSER_USE_COUNTS_KEY)
        reason = weighted_choice(pool, use_counts) or random.choice(pool)
        # Инкремент счётчика делаем здесь, до flush — попадает в ту же
        # транзакцию, что и сам ролл, и откатывается вместе с ним если
        # `on_announce` упадёт (для червя — другая ветка, там reason
        # фиксирован, счётчик трогать незачем).
        await increment_use_count(session, LOSER_USE_COUNTS_KEY, reason)

    row = LoserRoll(
        rolled_by=rolled_by.id,
        loser_user_id=loser.id,
        reason_text=reason,
        source=source,
    )
    session.add(row)
    await session.flush()  # populate row.id without committing

    # E8: если выпал червь — закрываем старую активную запись (если была)
    # и создаём новую. Делаем это ДО announce, чтобы откат транзакции при
    # ошибке отправки в TG откатывал и переход звания тоже.
    worm_event = WormEvent(chance_used=worm_chance)
    if is_worm:
        # T3.6 (г): если режим «червь-господин» включён — дописываем к анонсу
        # блок «что это даёт». Читаем пул и собираем готовый текст здесь (в
        # форматтер БД не тащим). chance — в процентах, без хвостовых нулей.
        from app.services.admin_config import (
            get_worm_announce_lines,
            is_worm_master_enabled,
        )

        if await is_worm_master_enabled(session):
            from app.services.worm_master import build_announce_extra

            lines = await get_worm_announce_lines(session)
            chance_pct = f"{worm_chance * 100:g}"
            worm_event.announce_extra = build_announce_extra(
                lines, username=loser.display_name, chance_pct=chance_pct
            )
    if is_worm:
        prev_worm = await session.scalar(
            select(WormAssignment).where(WormAssignment.ended_at.is_(None))
        )
        if prev_worm is not None:
            # Имя «бывшего червя» — для текста announce.
            prev_user = await session.get(User, prev_worm.user_id)
            worm_event.prev_worm_name = (
                prev_user.display_name if prev_user else None
            )
            # Не помечаем как «бывший червь = новый», если это тот же юзер
            # (червь повторно выпал тому же лицу). В этом случае —
            # продлеваем, не закрывая → не создаём новую строку.
            if prev_worm.user_id == loser.id:
                # Уже был червём — просто оставляем активную запись.
                worm_event.triggered = True
                if on_announce is not None:
                    try:
                        await on_announce(
                            row,
                            loser,
                            RollExtras(
                                worm=worm_event,
                                immunity_skipped=pick.skipped_names,
                            ),
                        )
                    except Exception:
                        await session.rollback()
                        raise
                await session.commit()
                await session.refresh(row)
                return row
            prev_worm.ended_at = datetime.now(timezone.utc)
            await session.flush()
        session.add(
            WormAssignment(
                user_id=loser.id,
                source_loser_roll_id=row.id,
            )
        )
        await session.flush()
        worm_event.triggered = True

    # T3.6 (а): если лох — действующий червь-господин (и это НЕ момент
    # становления червём), обрамляем обычный анонс подхалимажем. На worm-trigger
    # показывается особый анонс, подхалимаж туда не лепим.
    sycophancy = None
    if not is_worm:
        sycophancy = await resolve_master_sycophancy(session, loser)

    extras = RollExtras(
        worm=worm_event,
        immunity_skipped=pick.skipped_names,
        worm_master=sycophancy,
    )

    if on_announce is not None:
        try:
            await on_announce(row, loser, extras)
        except Exception:
            await session.rollback()
            raise

    await session.commit()
    await session.refresh(row)
    return row


async def get_current_worm(session: AsyncSession) -> WormAssignment | None:
    """Активный червь-пидор (≤1 строки с ended_at IS NULL). None если нет."""
    return await session.scalar(
        select(WormAssignment).where(WormAssignment.ended_at.is_(None))
    )


async def resolve_master_sycophancy(
    session: AsyncSession, user: User
) -> "MasterSycophancy | None":
    """T3.6 (а): подхалимский префикс/суффикс, если `user` — действующий
    червь-господин и режим worm_master включён. Иначе None.

    Выбор взвешенный (use_counts, чередование без частых повторов) с инкрементом
    счётчика — как у пула лоха. Переиспользуется анонсом чухана (T3.6.4).
    Сетевого IO нет: только SELECT/UPDATE в текущей транзакции.
    """
    from app.services.admin_config import (
        get_worm_master_prefixes,
        get_worm_master_suffixes,
        is_worm_master_enabled,
    )

    if not await is_worm_master_enabled(session):
        return None
    worm = await get_current_worm(session)
    if worm is None or worm.user_id != user.id:
        return None

    from app.services.phrase_weights import (
        WORM_MASTER_PREFIX_USE_COUNTS_KEY,
        WORM_MASTER_SUFFIX_USE_COUNTS_KEY,
    )
    from app.services.worm_master import choose, render

    name = user.display_name
    prefix_pool = await get_worm_master_prefixes(session)
    suffix_pool = await get_worm_master_suffixes(session)
    prefix_counts = await get_use_counts(session, WORM_MASTER_PREFIX_USE_COUNTS_KEY)
    suffix_counts = await get_use_counts(session, WORM_MASTER_SUFFIX_USE_COUNTS_KEY)

    raw_prefix = choose(prefix_pool, prefix_counts)
    raw_suffix = choose(suffix_pool, suffix_counts)
    prefix = None
    suffix = None
    if raw_prefix is not None:
        await increment_use_count(session, WORM_MASTER_PREFIX_USE_COUNTS_KEY, raw_prefix)
        prefix = render(raw_prefix, username=name)
    if raw_suffix is not None:
        await increment_use_count(session, WORM_MASTER_SUFFIX_USE_COUNTS_KEY, raw_suffix)
        suffix = render(raw_suffix, username=name)
    if prefix is None and suffix is None:
        return None
    return MasterSycophancy(prefix=prefix, suffix=suffix)


def decide_worm(*, enabled: bool, chance: float, rng_value: float) -> bool:
    """Чистая функция: выпадает ли «червь-пидор»?

    `rng_value` — число из `random.random()` (0 ≤ v < 1). Триггер: enabled AND
    chance > 0 AND rng_value < chance. Шанс ≤0 — никогда; ≥1 — всегда (clamp
    хранится при записи, здесь только сравнение). Возвращает bool.
    """
    if not enabled or chance <= 0.0:
        return False
    return rng_value < chance


def compose_loser_message(
    *,
    loser_name: str,
    reason_text: str,
    roller_name: str | None = None,
    loser_count: int | None = None,
    extras: RollExtras | None = None,
    header_emoji: str = "🎲",
    header_label: str = "Лох дня",
) -> str:
    """Единый шаблон HTML-сообщения о ролле лоха. Используется всеми callers
    (`routes_meetings.loser_roll`, `routes_admin.admin_loser_roll_now`,
    scheduler autoloser, chat_commands `/loser`).

    При выпадении «червя-пидора» (`extras.worm.triggered=True`) шаблон
    переключается на яркую форму: bold-хедер 🚨 ОСОБАЯ НОМИНАЦИЯ, имя
    выделено крупно, добавляется блок передачи звания (если был
    предыдущий носитель). Сами по себе reasons из пула — в этом сообщении
    не печатаются, потому что `reason_text` уже подменён на
    `WORM_REASON_TEXT`.
    """
    is_worm = bool(extras and extras.worm.triggered)

    if is_worm:
        lines = [
            "🚨 <b>ОСОБАЯ НОМИНАЦИЯ</b> 🚨",
            "",
            f"🪱 <b>{loser_name}</b> — ты <b>ЧЕРВЬ-ПИДОР</b>!",
            "",
            "Это редчайшее звание. Носи с честью (или с позором).",
        ]
        prev = extras.worm.prev_worm_name if extras else None
        if prev and prev != loser_name:
            lines.append("")
            lines.append(
                f"<i>Старый червь «{prev}» слагает полномочия. "
                f"Корона переходит.</i>"
            )
        # T3.6 (г): расширение «что даёт звание господина» (если режим включён).
        # Ставим ДО роллера/счётчика — это смысловая часть анонса.
        announce_extra = extras.worm.announce_extra if extras else None
        if announce_extra:
            lines.append("")
            lines.append(announce_extra)
        if roller_name:
            lines.append("")
            lines.append(f"<i>Покрутил рулетку: {roller_name}</i>")
        # Лох-счётчик прибавляется тоже — пишем мелко, чтобы не отвлекать
        # от основного эффекта.
        if loser_count is not None:
            lines.append(f"<i>(Заодно {loser_count}-й раз становится лохом.)</i>")
        return "\n".join(lines)

    # Обычный лох
    sycophancy = extras.worm_master if extras else None

    lines: list[str] = []
    # T3.6 (а): подхалимский префикс — отдельной строкой ПЕРЕД хедером.
    if sycophancy and sycophancy.prefix:
        lines.append(f"<i>{sycophancy.prefix}</i>")
    lines.append(f"{header_emoji} <b>{header_label}</b> — {loser_name}!")
    if reason_text:
        lines.append(f"Причина: {reason_text}")
    if loser_count is not None:
        lines.append(f"Уже {loser_count}-й раз становится лохом.")
    if roller_name:
        lines.append(f"<i>Покрутил рулетку: {roller_name}</i>")
    # T3.6 (а): подхалимский суффикс — последней строкой ПОСЛЕ всего.
    if sycophancy and sycophancy.suffix:
        lines.append(f"<i>{sycophancy.suffix}</i>")
    return "\n".join(lines)


async def delete_last_loser(session: AsyncSession) -> LoserRoll | None:
    """Drop the most recent loser roll (for manual re-roll). Returns the
    deleted row or None if there was nothing to delete."""
    row = await session.scalar(
        select(LoserRoll).order_by(desc(LoserRoll.rolled_at)).limit(1)
    )
    if row is None:
        return None
    await session.delete(row)
    await session.commit()
    return row


async def loser_stats(session: AsyncSession) -> dict[int, int]:
    # GHG7 P9.2.a: «автолох-дуэль» (source='duel', /loser + LoserSheet) НЕ идёт
    # в статистику — это развлекательный ручной прокрут, не официальный «лох
    # дня». Считаем только auto/manual (и legacy-NULL до появления source).
    rows = (
        await session.execute(
            select(LoserRoll.loser_user_id, func.count())
            .where(or_(LoserRoll.source != "duel", LoserRoll.source.is_(None)))
            .group_by(LoserRoll.loser_user_id)
        )
    ).all()
    return {uid: int(cnt) for uid, cnt in rows}


async def last_loser(session: AsyncSession) -> LoserRoll | None:
    return await session.scalar(select(LoserRoll).order_by(desc(LoserRoll.rolled_at)).limit(1))


class CooldownError(Exception):
    def __init__(self, remaining: timedelta):
        self.remaining = remaining
        super().__init__(f"cooldown {remaining}")
