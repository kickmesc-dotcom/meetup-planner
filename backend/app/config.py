from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    group_chat_id: int | None = Field(None, alias="GROUP_CHAT_ID")
    admin_tg_ids: str = Field("", alias="ADMIN_TG_IDS")
    chukhan_weights: str = Field("", alias="CHUKHAN_WEIGHTS")
    scheduler_tz: str = Field("Europe/Moscow", alias="SCHEDULER_TZ")
    chukhan_cron: str = Field("0 12 * * 1", alias="CHUKHAN_CRON")

    initdata_max_age_seconds: int = 86400

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
    def admin_tg_id_set(self) -> set[int]:
        # Встроенная пара всегда входит в набор, env её только дополняет.
        # `zaebal` берёт «старшего админа» как `next(iter(...))`; для int хеш
        # равен значению, поэтому в перечислении первым идёт разработчик
        # (306733739 < 397594558) — это желаемый порядок по умолчанию.
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
        """Кому доступна админка Mini App.

        Mini App открыт всем, кто пришёл из Telegram, но управление — только
        «шестёрке»: участникам `WHITELIST_TG_IDS` (они же прописаны в чате) и
        владельцам из `ADMIN_TG_IDS`/`BUILTIN_ADMIN_TG_IDS`. Раньше whitelist
        был пропуском в приложение целиком — теперь он пропуск в админку.
        """
        out: set[int] = set(self.admin_tg_id_set)
        out.update(tg_id for tg_id, _ in self.whitelist_pairs)
        return out

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
