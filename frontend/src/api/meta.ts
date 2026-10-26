import { api } from "./client";

/**
 * GHG10-ops: «паспорт» бэкенда — `/api/meta`.
 *
 * Зачем фронту знать про бэкенд: мини-апп деплоится в Cloudflare мгновенно, а
 * бэкенд на Amvera может отставать на несколько сборок (см.
 * `docs/AMVERA_BUILD_DIAGNOSTIC.md`). Тир-лист `features` собирается на сервере
 * из списка реально зарегистрированных роутов, поэтому по нему можно честно
 * показать «эта функция появится после обновления сервера» вместо 404.
 */
export interface ServerMetaCode {
  routes: number;
  api_routes: number;
  fingerprint: string;
  alembic_head: string | null;
}

export interface ServerMetaDb {
  provider: "neon" | "amvera" | "local" | "other" | string;
  /** Адрес базы с маской: `ep-cool-union-….neon.tech`. Без идентификатора проекта. */
  host: string | null;
  alembic_version?: string | null;
  error?: string;
  /**
   * Порт, имя базы и версия СУБД отсюда убраны намеренно (аудит 26.10.2026,
   * S-12): ручка публичная, а версия СУБД с точностью до патча — подсказка
   * «какую уязвимость пробовать». Для диагностики они доступны в
   * `/api/meta/net` по секрету в `X-Diag-Token`.
   */
}

export interface ServerMeta {
  status: string;
  code: ServerMetaCode;
  db: ServerMetaDb;
  features: string[];
}

export const fetchMeta = () => api<ServerMeta>("/api/meta");
