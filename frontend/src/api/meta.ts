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
  host: string | null;
  port: number | null;
  name: string | null;
  alembic_version?: string | null;
  server_version?: string | null;
  error?: string;
}

export interface ServerMeta {
  status: string;
  code: ServerMetaCode;
  db: ServerMetaDb;
  features: string[];
}

export const fetchMeta = () => api<ServerMeta>("/api/meta");
