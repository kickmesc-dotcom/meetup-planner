"""Свой бот и свой чат у организации (B2B_PLATFORM_PLAN, шаг 1.6).

До этого шага бот был один на всех: `BOT_TOKEN` и `GROUP_CHAT_ID` из env. Для
B2B это стоп-фактор — клиент приходит со своим ботом (своё имя, своя аватарка,
свои команды), и второй клиент не должен писать в чужой чат.

Что здесь есть:

* `organizations.bot_token`, `webhook_secret`, `group_chat_id` — данные бота;
* этот модуль — реестр «организация → бот/чат» в памяти процесса;
* пустые поля означают «как раньше»: бот и чат берутся из env. Поэтому
  существующий контур работает без изменений, а новый клиент просто получает
  свою строку.

Почему реестр, а не запрос в базу на каждый вызов. `get_bot()` и
`settings.group_chat_id` вызываются из 150 мест, в том числе из синхронного
кода и из планировщика. Реестр наполняется один раз при старте (и обновляется
при входящем вебхуке/правке настроек), а дальше чтение — обычный словарь.

Секрет вебхука — единственный якорь, по которому апдейт находит организацию:
тело запроса подписано ботом, но до проверки подписи мы не знаем, чей это бот.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.org_models import DEFAULT_ORG_ID, Organization, current_org_id


@dataclass(frozen=True)
class OrgBotConfig:
    """Всё, что нужно, чтобы говорить от имени организации."""

    org_id: int
    slug: str
    token: str | None
    chat_id: int | None
    webhook_secret: str | None
    # Токен из строки организации, а не подставленный из env. Различие важно:
    # env-бот обслуживает организацию по умолчанию, но отдельный вебхук и
    # отдельный Bot ему не нужны — он уже есть.
    own_bot: bool = False


_registry: dict[int, OrgBotConfig] = {}
_loaded = False


def _env_defaults() -> tuple[str | None, int | None]:
    """Бот и чат из env — обслуживают организацию по умолчанию."""
    from app.config import get_settings

    settings = get_settings()
    # `getattr` — для тестов, которые подменяют настройки простым объектом.
    return settings.bot_token, getattr(settings, "group_chat_id_env", None)


async def reload(session: AsyncSession) -> int:
    """Перечитать организации. Возвращает число записей в реестре.

    Вызывается на старте и после правки настроек бота: держать реестр в
    согласии с базой дешевле, чем проверять его на каждом апдейте.
    """
    global _loaded
    rows = list(
        await session.scalars(
            select(Organization)
            .where(Organization.is_active.is_(True))
            .order_by(Organization.id)
        )
    )
    env_token, env_chat = _env_defaults()
    fresh: dict[int, OrgBotConfig] = {}
    for org in rows:
        token = org.bot_token or (env_token if org.id == DEFAULT_ORG_ID else None)
        chat = org.group_chat_id
        if chat is None and org.id == DEFAULT_ORG_ID:
            chat = env_chat
        secret = org.webhook_secret
        if secret is None and org.id == DEFAULT_ORG_ID:
            secret = _env_webhook_secret()
        fresh[org.id] = OrgBotConfig(
            org_id=org.id,
            slug=org.slug,
            token=token,
            chat_id=chat,
            webhook_secret=secret,
            own_bot=bool(org.bot_token),
        )
    _registry.clear()
    _registry.update(fresh)
    _loaded = True
    return len(_registry)


def _env_webhook_secret() -> str | None:
    from app.config import get_settings

    return get_settings().tg_webhook_secret


async def ensure_loaded(session: AsyncSession) -> None:
    if not _loaded:
        await reload(session)


def loaded() -> bool:
    return _loaded


def reset() -> None:
    """Забыть реестр (тесты и выход из приложения)."""
    global _loaded
    _registry.clear()
    _loaded = False


def config(org_id: int) -> OrgBotConfig | None:
    return _registry.get(org_id)


def all_configs() -> list[OrgBotConfig]:
    return list(_registry.values())


def current() -> OrgBotConfig | None:
    return _registry.get(current_org_id.get())


def token_for(org_id: int) -> str | None:
    """Токен бота организации; для неизвестной организации — env-бот.

    Возвращает `None` только если нет ни своего, ни env-токена: тогда вызывающий
    обязан внятно упасть, а не молча работать от чужого имени.
    """
    cfg = _registry.get(org_id)
    if cfg is not None and cfg.token:
        return cfg.token
    env_token, _ = _env_defaults()
    return env_token


def chat_id_for(org_id: int) -> int | None:
    cfg = _registry.get(org_id)
    if cfg is not None and cfg.chat_id is not None:
        return cfg.chat_id
    _, env_chat = _env_defaults()
    return env_chat


def chat_id_for_current_org() -> int | None:
    return chat_id_for(current_org_id.get())


def org_for_webhook_secret(secret: str) -> int | None:
    """Организация по секрету вебхука. `None` — такого бота мы не обслуживаем.

    Сравнение — `hmac.compare_digest`, а не `==` (аудит 26.10.2026, S-13):
    обычное сравнение строк выходит на первом различии, и по времени ответа
    секрет в теории можно подобрать посимвольно. По сети это почти неизмеримо,
    но правильная функция здесь стоит ровно столько же, сколько неправильная.
    """
    return _org_by_secret_value(secret, key="webhook_secret")


def org_for_token(token: str) -> int | None:
    """Чей это токен бота. Сравнение — тоже constant-time."""
    return _org_by_secret_value(token, key="token")


def _org_by_secret_value(value: str, *, key: str) -> int | None:
    """Найти организацию, у которой секрет/токен совпадает с `value`.

    Перебираем все записи без ранних выходов: выход по `return` внутри цикла
    сам по себе сообщает, на каком месте совпало.
    """
    found: int | None = None
    raw = (value or "").encode("utf-8")
    for cfg in _registry.values():
        candidate = getattr(cfg, key)
        if not candidate or not raw:
            continue
        # Сравниваем байты, а не строки: `compare_digest` для `str` принимает
        # только ASCII, а в заголовке от чужого клиента может прийти что угодно —
        # тогда был бы `TypeError` и 500 вместо честного 403.
        if hmac.compare_digest(candidate.encode("utf-8"), raw):
            found = cfg.org_id
    return found


def token_candidates() -> list[str]:
    """Токены, которыми может быть подписан `initData` мини-аппа.

    Сначала env-бот (текущий контур), затем боты организаций. Дубликаты
    убираем: у организации по умолчанию токен тот же самый.
    """
    env_token, _ = _env_defaults()
    tokens: list[str] = []
    if env_token:
        tokens.append(env_token)
    for cfg in _registry.values():
        if cfg.token and cfg.token not in tokens:
            tokens.append(cfg.token)
    return tokens


def orgs_with_own_bot() -> list[OrgBotConfig]:
    """Организации, у которых свой токен: им нужен отдельный вебхук."""
    return [cfg for cfg in _registry.values() if cfg.own_bot]
