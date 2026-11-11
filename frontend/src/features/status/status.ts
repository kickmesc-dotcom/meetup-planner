/**
 * Логика статус-страницы без React: её проще проверить и невозможно «случайно»
 * показать зелёный статус при ошибке базы.
 */
export interface Meta {
  status: string;
  code: { build?: string | null; source?: string | null };
  db: {
    provider?: string | null;
    host?: string | null;
    alembic_version?: string | null;
    error?: string | null;
  };
}

export interface StatusView {
  ok: boolean;
  dbOk: boolean;
  dbError: string | null;
  build: string;
  version: string;
  provider: string;
}

/** `/status` и `/status/` — один экран; любой другой путь — приложение. */
export function isStatusPath(pathname: string): boolean {
  return pathname.replace(/\/+$/, "") === "/status";
}

export function statusView(meta: Meta): StatusView {
  const dbError = meta.db.error ?? null;
  // «ok» от процесса ничего не значит, если база недоступна: приложение без
  // данных не работает, и зелёная плашка была бы враньём.
  return {
    ok: meta.status === "ok" && dbError === null,
    dbOk: dbError === null,
    dbError,
    build: meta.code.build?.trim() || "—",
    version: meta.db.alembic_version?.trim() || "—",
    provider: meta.db.provider?.trim() || "—",
  };
}
