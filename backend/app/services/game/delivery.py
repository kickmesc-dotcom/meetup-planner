"""GHG11: единая модель доставки бота — «одна дверь» для всех фич.

Оператор устал от разнобоя «вкл/выкл» и «чат/приложение». Теперь КАЖДАЯ фича
бота (кроме модуля ачивок — он строго отдельный) описывается одним из ЧЕТЫРЁХ
состояний:

* ``off``  — фича выключена (при попытке триггера — заглушка «фича выключена»);
* ``chat`` — всё как раньше, активность идёт в общий чат;
* ``app``  — активность видна ТОЛЬКО в ленте мини-аппа, в чат бот молчит;
* ``both`` — активность идёт в чат и дублируется в ленте мини-аппа.

Над фичами стоят два МАСТЕР-свитчера:

* ``general``      — все фичи, КРОМЕ ачивок;
* ``achievements`` — только модуль ачивок (сбор/выдача/анонсы).

Мастер-свитчер «принудительно» переводит все свои фичи в одно из четырёх
состояний. Если затем тронуть отдельную фичу — её значение разъедется с
мастером, и мастер сам покажет статус ``custom``.

Чтение конфига безопасно: любой сбой (нет сессии, тестовая fake-сессия без
``admin_config``) трактуется как дефолт ``chat`` — лучше показать сообщение в
чате, чем молча потерять поведение, к которому чат привык.
"""
from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# --- Состояния -------------------------------------------------------------

MODE_OFF = "off"
MODE_CHAT = "chat"
MODE_APP = "app"
MODE_BOTH = "both"
MODES: tuple[str, ...] = (MODE_OFF, MODE_CHAT, MODE_APP, MODE_BOTH)
MODE_LABELS: dict[str, str] = {
    MODE_OFF: "Выкл",
    MODE_CHAT: "Только в чате",
    MODE_APP: "Только в мини-аппе",
    MODE_BOTH: "Чат + мини-апп",
}

# Мастер-модули.
MODULE_GENERAL = "general"
MODULE_ACHIEVEMENTS = "achievements"
MODULES: tuple[str, ...] = (MODULE_GENERAL, MODULE_ACHIEVEMENTS)
CUSTOM = "custom"  # виртуальный статус мастера: фичи разъехались

DEFAULT_MODE = MODE_CHAT

# Ключи в admin_config.
MASTER_KEY_PREFIX = "delivery.master."
FEATURE_KEY_PREFIX = "delivery.feature."


@dataclass(frozen=True)
class Feature:
    """Описание фичи для реестра и админки."""

    key: str
    label: str
    module: str = MODULE_GENERAL
    # Для мини-аппа: короткая подсказка, что происходит в режиме «только апп».
    hint: str = ""
    default: str = DEFAULT_MODE


# Реестр ВСЕХ фич бота. Порядок = порядок в админке.
FEATURES: tuple[Feature, ...] = (
    # --- Планер и встречи ---
    Feature("meetings", "Планер встреч", hint="календарь, авто-подбор, назначение"),
    # --- Игра ---
    Feature("loser_manual", "Лох-рулетка (ручная)", hint="результат ролла в ленте"),
    Feature("loser_auto", "Автолох (по расписанию)", hint="ежедневный ролл в ленте"),
    Feature("chukhan", "Чухан недели", hint="итоги недели в ленте"),
    Feature("phrases", "Прогон фраз", hint="фраза бота в ленте"),
    Feature("events", "Случайные события", hint="вопросы и ответы в ленте"),
    Feature("advice", "Магический шар", hint="совет в ленте"),
    Feature("worm", "Червь", hint="поддакивания и кара в ленте"),
    Feature("contraband", "Контрабанда слов", hint="находки в ленте"),
    Feature("memorial", "Поминовения", hint="поминовения в ленте"),
    Feature("dead_chat", "Мёртвый чат", hint="оживление в ленте"),
    Feature("voice", "Голосовые задания", hint="задания и приём вариантов"),
    Feature("voice_poll", "Опрос «чей вариант лучше»", hint="голосование в ленте"),
    Feature("music", "Музыкальная предложка", hint="подборки и лайки"),
    Feature("music_game", "Мьюзик-гейм", hint="угадай автора в ленте"),
    Feature("nominations", "Номинации и голосования", hint="номинации и опросы"),
    Feature("media_reactions", "Реакции на медиа", hint="симуляция чата"),
    Feature("chat_reactions", "Реакции чата", hint="симуляция чата"),
    # --- Ачивки (отдельный модуль) ---
    Feature(
        "achievements",
        "Ачивки",
        module=MODULE_ACHIEVEMENTS,
        hint="выдача и анонсы достижений",
    ),
)

FEATURE_BY_KEY: dict[str, Feature] = {f.key: f for f in FEATURES}


def features_of(module: str) -> tuple[Feature, ...]:
    return tuple(f for f in FEATURES if f.module == module)


def is_valid_mode(mode: str | None) -> bool:
    return mode in MODES


def feature(label: str) -> Feature:
    """Вернуть описание фичи по ключу (KeyError → пустой Feature-safe)."""
    return FEATURE_BY_KEY[label]


# --- Чистые решения по режиму (тестируются без БД) -------------------------


def chat_enabled(mode: str) -> bool:
    """Уходит ли активность в общий чат."""
    return mode in (MODE_CHAT, MODE_BOTH)


def app_enabled(mode: str) -> bool:
    """Видна ли активность в ленте мини-аппа."""
    return mode in (MODE_APP, MODE_BOTH)


def is_active(mode: str) -> bool:
    """Фича вообще включена (не ``off``)."""
    return mode != MODE_OFF


# --- Чтение конфига --------------------------------------------------------


async def _raw_feature_mode(session: AsyncSession, key: str) -> str | None:
    from app.services.admin_config import _get_value

    raw = await _get_value(session, f"{FEATURE_KEY_PREFIX}{key}")
    return raw if raw in MODES else None


async def _raw_master(session: AsyncSession, module: str) -> str | None:
    from app.services.admin_config import _get_value

    raw = await _get_value(session, f"{MASTER_KEY_PREFIX}{module}")
    return raw if raw in MODES else None


async def get_feature_mode(session: AsyncSession | None, key: str) -> str:
    """Эффективный режим фичи: её оверрайд → мастер её модуля → дефолт.

    Без сессии/при сбое чтения — безопасный ``chat``.
    """
    spec = FEATURE_BY_KEY.get(key)
    default = spec.default if spec is not None else DEFAULT_MODE
    module = spec.module if spec is not None else MODULE_GENERAL
    try:
        if session is None:
            from app.db.base import get_sessionmaker

            sm = get_sessionmaker()
            async with sm() as own:
                return await _resolve(own, key, module, default)
        return await _resolve(session, key, module, default)
    except Exception as exc:  # noqa: BLE001
        log.warning("game.delivery_read_failed", feature=key, error=str(exc))
        return default


async def _resolve(
    session: AsyncSession, key: str, module: str, default: str
) -> str:
    own = await _raw_feature_mode(session, key)
    if own is not None:
        return own
    master = await _raw_master(session, module)
    if master is not None:
        return master
    return default


async def get_mode_map(session: AsyncSession) -> dict[str, str]:
    """Эффективные режимы всех фич одним словарём (для админки/ленты)."""
    out: dict[str, str] = {}
    for spec in FEATURES:
        raw = await _raw_feature_mode(session, spec.key)
        if raw is not None:
            out[spec.key] = raw
            continue
        master = await _raw_master(session, spec.module)
        out[spec.key] = master if master is not None else spec.default
    return out


async def get_master_status(session: AsyncSession, module: str) -> str:
    """Статус мастер-свитчера: одно из 4 состояний или ``custom``.

    Выводится ИЗ ТЕКУЩИХ значений фич модуля, а не хранится отдельно — иначе
    мастер «врал» бы после точечных правок. ``custom`` — фичи разъехались.
    """
    modes = {await get_feature_mode(session, f.key) for f in features_of(module)}
    if len(modes) == 1:
        return next(iter(modes))
    return CUSTOM


# --- Запись конфига --------------------------------------------------------


async def set_feature_mode(session: AsyncSession, key: str, mode: str) -> None:
    if key not in FEATURE_BY_KEY:
        raise ValueError(f"unknown feature: {key!r}")
    if mode not in MODES:
        raise ValueError(f"bad mode: {mode!r}")
    from app.services.admin_config import _set_value

    await _set_value(session, f"{FEATURE_KEY_PREFIX}{key}", mode)


async def set_master_mode(session: AsyncSession, module: str, mode: str) -> None:
    """Принудительно перевести ВСЕ фичи модуля в ``mode``."""
    if module not in MODULES:
        raise ValueError(f"unknown module: {module!r}")
    if mode not in MODES:
        raise ValueError(f"bad mode: {mode!r}")
    from app.services.admin_config import _set_value

    await _set_value(session, f"{MASTER_KEY_PREFIX}{module}", mode)
    for spec in features_of(module):
        await _set_value(session, f"{FEATURE_KEY_PREFIX}{spec.key}", mode)
