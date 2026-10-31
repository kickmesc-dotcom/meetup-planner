from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_REPO = "kickmesc-dotcom/meetup-planner"

# Origin превью-развёртываний Cloudflare Pages (<hash>.semitaskbot.pages.dev)
# и локальной разработки. Вынесено из среды в код, потому что забытая строка
# здесь ломает не безопасность, а работу: мини-апп на свежем превью перестал бы
# ходить в API. Список продуктовых доменов сюда не входит — они берутся из
# `MINI_APP_URL`/`APP_PUBLIC_URL` и `CORS_ORIGINS`.
DEFAULT_CORS_ORIGIN_REGEX = (
    r"https://([a-z0-9-]+\.)*semitaskbot\.pages\.dev"
    r"|http://localhost(:\d+)?"
    r"|http://127\.0\.0\.1(:\d+)?"
)

# Чужие Origin-«ловушки» для проверки заданной извне регулярки CORS.
#
# История (аудит 26.10.2026, S-1b). В коде белый список Origin уже был: при
# `CORS_ORIGINS` со списком `*` не применяется, а с `*` выключаются credentials.
# Но живая проба на боевом Space 26.10.2026 всё равно получила
# `access-control-allow-origin: https://evil.example.com` вместе с
# `allow-credentials: true`. Причина — переменная окружения `CORS_ORIGIN_REGEX`,
# оставшаяся с прошлых запусков: широкий шаблон вроде `https://.*` заставляет
# Starlette отражать ЛЮБОЙ сайт. То есть одна забытая переменная молча обнуляла
# защиту, и по коду этого не было видно. Поэтому чужой шаблон теперь проверяется
# на ловушках и, если он их пускает, в дело не идёт.
CORS_ORIGIN_CANARIES = (
    "https://evil.example.com",
    "http://evil.example.com",
    "https://cors-canary.invalid",
)


def cors_regex_allows_foreign(pattern: str) -> bool:
    """Пустит ли эта регулярка хоть один чужой Origin.

    Невалидную регулярку тоже считаем опасной: разобрать её смысл нельзя, а
    Starlette на битом шаблоне не падает — просто не пускает никого, и внешне
    это выглядит как «CORS сломался», что диагностируется часами.
    """
    try:
        compiled = re.compile(pattern)
    except re.error:
        return True
    for canary in CORS_ORIGIN_CANARIES:
        # `fullmatch` — семантика свежего Starlette (`is_allowed_origin`),
        # `match` — на случай версии, которая сверяет только начало строки:
        # обе должны быть безопасны, иначе `https://.*` снова открыл бы всех.
        if compiled.fullmatch(canary) or compiled.match(canary):
            return True
    return False


def origin_of_url(url: str) -> str:
    """`https://host:port` из адреса или `""`, если адреса нет/он не абсолютный."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(..., alias="BOT_TOKEN")
    tg_webhook_secret: str = Field(..., alias="TG_WEBHOOK_SECRET")
    mini_app_url: str = Field(..., alias="MINI_APP_URL")
    public_base_url: str = Field("", alias="PUBLIC_BASE_URL")

    database_url: str = Field(..., alias="DATABASE_URL")

    whitelist_tg_ids: str = Field("", alias="WHITELIST_TG_IDS")
    whitelist_names: str = Field(
        "Дмитрий Menar,Сергей Neo,Дмитрий Повар,Никита,Дмитрий-JDM,Русланище",
        alias="WHITELIST_NAMES",
    )

    cors_origins: str = Field("*", alias="CORS_ORIGINS")
    # Origin превью-развёртываний Pages и локальной разработки. Регулярка, а не
    # список: у Cloudflare Pages адрес превью меняется на каждую сборку
    # (`<hash>.semitaskbot.pages.dev`), и перечислять их поимённо бессмысленно.
    cors_origin_regex: str = Field(DEFAULT_CORS_ORIGIN_REGEX, alias="CORS_ORIGIN_REGEX")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # Чат ОРГАНИЗАЦИИ ПО УМОЛЧАНИЮ. У клиента со своим ботом чат лежит в
    # `organizations.group_chat_id`, а наружу торчит свойство `group_chat_id`
    # ниже — иначе пришлось бы править 85 вызовов `settings.group_chat_id` и
    # надеяться, что ни один не забыт (B2B_PLATFORM_PLAN, шаг 1.6).
    group_chat_id_env: int | None = Field(None, alias="GROUP_CHAT_ID")
    admin_tg_ids: str = Field("", alias="ADMIN_TG_IDS")
    chukhan_weights: str = Field("", alias="CHUKHAN_WEIGHTS")
    scheduler_tz: str = Field("Europe/Moscow", alias="SCHEDULER_TZ")
    chukhan_cron: str = Field("0 12 * * 1", alias="CHUKHAN_CRON")

    initdata_max_age_seconds: int = 86400

    # --- Вход без Telegram (B2B_PLATFORM_PLAN, 2.1) -----------------------
    # Куда ведёт ссылка из письма и с какого адреса уходят письма.
    app_public_url: str = Field("", alias="APP_PUBLIC_URL")
    mail_from: str = Field("SemiTaskBot <no-reply@localhost>", alias="MAIL_FROM")
    # Транспорт выбирается тем, что заполнено: Resend (HTTP) или SMTP (любой
    # провайдер, включая Яндекс 360). Пусто — режим «лог» без отправки.
    resend_api_key: str = Field("", alias="RESEND_API_KEY")
    smtp_host: str = Field("", alias="SMTP_HOST")
    smtp_port: int = Field(465, alias="SMTP_PORT")
    smtp_user: str = Field("", alias="SMTP_USER")
    smtp_password: str = Field("", alias="SMTP_PASSWORD")
    smtp_starttls: bool = Field(True, alias="SMTP_STARTTLS")
    auth_session_days: int = Field(30, alias="AUTH_SESSION_DAYS")

    # --- Push вне Telegram (B2B_PLATFORM_PLAN, шаг 2.4) -------------------
    # Пара VAPID: публичная уходит в браузер, приватная остаётся на сервере.
    # Пусто — push выключен: кнопки в приложении нет, напоминания идут как
    # раньше (колокольчик + Telegram), ничего не падает.
    vapid_public_key: str = Field("", alias="VAPID_PUBLIC_KEY")
    vapid_private_key: str = Field("", alias="VAPID_PRIVATE_KEY")
    # Идентификатор отправителя для push-сервиса: `mailto:` или URL сайта.
    vapid_subject: str = Field(
        "mailto:no-reply@semitask.bot", alias="VAPID_SUBJECT"
    )

    @property
    def link_base(self) -> str:
        """База для ссылок в письмах: без хвостового слэша."""
        raw = self.app_public_url or self.mini_app_url
        return raw.rstrip("/")

    # `/changelog`: откуда брать коммиты. Токен не обязателен для публичного
    # репозитория, но с ним выше лимит GitHub и работает приватный репо.
    github_repo: str = Field(DEFAULT_REPO, alias="GITHUB_REPO")
    github_token: str = Field("", alias="GITHUB_TOKEN")

    @property
    def group_chat_id(self) -> int | None:
        """Чат текущей организации, с откатом на env.

        Свойство, а не поле: чат зависит от того, чей запрос/апдейт сейчас
        выполняется, а не от конфигурации процесса. Реестр организаций
        импортируется лениво — `config` читают почти все модули, и жёсткий
        импорт дал бы цикл.
        """
        from app.services import org_bots

        return org_bots.chat_id_for_current_org()

    @property
    def whitelist_pairs(self) -> list[tuple[int, str]]:
        ids = [s.strip() for s in self.whitelist_tg_ids.split(",") if s.strip()]
        names = [s.strip() for s in self.whitelist_names.split(",") if s.strip()]
        if not ids:
            return []
        out: list[tuple[int, str]] = []
        for i, raw in enumerate(ids):
            try:
                tg_id = int(raw)
            except ValueError:
                continue
            name = names[i] if i < len(names) else f"User {tg_id}"
            out.append((tg_id, name))
        return out

    @property
    def cors_origin_list(self) -> list[str]:
        return [s.strip() for s in self.cors_origins.split(",") if s.strip()]

    @property
    def cors_allow_all(self) -> bool:
        """Разрешены ли все Origin (в `CORS_ORIGINS` стоит `*` или пусто)."""
        origins = self.cors_origin_list
        return not origins or "*" in origins

    @property
    def cors_own_origins(self) -> list[str]:
        """Origin, с которых работает наше же приложение.

        Мини-апп и веб-версия живут на этих адресах, и запросы к API уходят
        именно с них. Поэтому они разрешены всегда, независимо от того, что
        лежит в `CORS_ORIGINS`: иначе приложение сломалось бы от того, что
        владелец забыл вписать свой домен в переменную.
        """
        out: list[str] = []
        for raw in (self.mini_app_url, self.app_public_url):
            origin = origin_of_url(raw)
            if origin and origin not in out:
                out.append(origin)
        return out

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Итоговый белый список Origin для CORSMiddleware."""
        if self.cors_allow_all:
            return ["*"]
        merged = [*self.cors_origin_list, *self.cors_own_origins]
        # `dict.fromkeys` — дедуликация с сохранением порядка для читаемого конфига.
        return list(dict.fromkeys(merged))

    @property
    def cors_origin_regex_rejected(self) -> bool:
        """Отброшена ли заданная извне регулярка как «пускающая всех».

        Отдельным свойством, а не только логом: значение видно в диагностике
        (`/api/meta/net`), поэтому на вопрос «почему на хосте CORS шире, чем в
        коде» отвечает сам хост, а не догадка.
        """
        raw = (self.cors_origin_regex or "").strip()
        if not raw or raw.lower() in {"off", "none", "false"}:
            return False
        return cors_regex_allows_foreign(raw)

    @property
    def cors_origin_regex_or_none(self) -> str | None:
        """Регулярка превью/локалки. `""` или `off` — выключено.

        Регулярка, пришедшая из среды, проходит проверку на ловушках (см.
        `cors_regex_allows_foreign`): широкая вроде `https://.*` вернула бы
        отражение любого Origin, поэтому вместо неё берётся встроенный шаблон.
        Полезного при этом не теряем: превью-развёртывания Pages и локальную
        разработку встроенный шаблон разрешает сам (см.
        `DEFAULT_CORS_ORIGIN_REGEX`).
        """
        raw = (self.cors_origin_regex or "").strip()
        if not raw or raw.lower() in {"off", "none", "false"}:
            return None
        if self.cors_origin_regex_rejected:
            return DEFAULT_CORS_ORIGIN_REGEX
        return raw

    @property
    def cors_credentials_allowed(self) -> bool:
        """Можно ли разрешать `credentials` при таком списке Origin.

        `*` вместе с `allow_credentials=True` — это не «звёздочка в ответе»:
        Starlette в этом случае подставляет в `Access-Control-Allow-Origin`
        Origin запроса, то есть разрешает любой сайт. Прод-проба 26.10.2026
        это подтвердила (см. `docs/AUDIT_SECURITY_STABILITY.md`, S-1), поэтому
        при `*` credentials выключаются принудительно.
        """
        return not self.cors_allow_all

    @property
    def admin_tg_id_set(self) -> set[int]:
        # Встроенная пара всегда входит в набор, env её только дополняет.
        # Порядок перебора фиксирован значениями int (младший tg_id первым),
        # поэтому «старший админ» — это разработчик, а не случайный человек.
        out: set[int] = set(BUILTIN_ADMIN_TG_IDS)
        for raw in self.admin_tg_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.add(int(raw))
            except ValueError:
                continue
        return out

    @property
    def staff_tg_id_set(self) -> set[int]:
        """Кому доступна админка Mini App: только владельцы продукта.

        Источник — `ADMIN_TG_IDS` плюс встроенная пара `BUILTIN_ADMIN_TG_IDS`.
        `WHITELIST_TG_IDS` сюда больше НЕ входит: раньше «пропуск в проект» и
        «права редактора» были одной переменной, и каждый, кого вписали в
        чат, автоматически становился админом приложения (31.10.2026).

        Права клиентов из env не берутся вообще. Клиентская команда получает
        их из базы: `org_members.role` → `owner` = admin, `manager` = aup,
        `staff` = employee (см. `services/hr_access._ORG_ROLE_TO_HR`). Иначе
        пришлось бы править переменные окружения на каждого нового клиента —
        а для входа без Telegram это просто невозможно.
        """
        return set(self.admin_tg_id_set)

    @property
    def chukhan_weight_map(self) -> dict[int, float]:
        """`CHUKHAN_WEIGHTS` is a comma list of `tg_id:weight` pairs.
        Empty/missing weights default to 1.0 in the service."""
        out: dict[int, float] = {}
        for chunk in self.chukhan_weights.split(","):
            chunk = chunk.strip()
            if not chunk or ":" not in chunk:
                continue
            tg, w = chunk.split(":", 1)
            try:
                out[int(tg.strip())] = max(0.0, float(w.strip()))
            except ValueError:
                continue
        return out


# Владельцы и кураторы проекта: два человека, у которых доступ «ко всему» с
# первого запуска, без правки env. 306733739 — разработчик, 397594558 —
# управляющий (второй куратор). Держим их в коде, а не только в `.env`: если
# `ADMIN_TG_IDS` в окружении забыли, максимум доступа всё равно должен быть у
# тех, кто этот проект ведёт.
BUILTIN_ADMIN_TG_IDS: tuple[int, ...] = (306733739, 397594558)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
