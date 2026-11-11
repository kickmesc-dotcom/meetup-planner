import { api } from "./client";

/**
 * Приватность организации (B2B_PLATFORM_PLAN, шаг 5.5).
 *
 * Числа сроков приходят с сервера, а не пишутся на экране: обещание в
 * документе и поведение сервера должны быть одним числом. Если завтра срок
 * корзины изменится, экран изменится вместе с ним.
 */
export interface PrivacyRetention {
  audit_days: number;
  deletion_grace_days: number;
  fired_trash_days: number;
  backup_artifact_days: number;
}

export interface DeletionState {
  deleted: boolean;
  deleted_at: string | null;
  purge_after: string | null;
  days_left: number | null;
}

export interface PrivacyState {
  /** Код организации: его вводят, чтобы подтвердить удаление. */
  slug: string;
  retention: PrivacyRetention;
  deletion: DeletionState;
}

export interface AuditEvent {
  id: number;
  action: string;
  actor_name: string | null;
  target_type: string | null;
  target_id: string | null;
  details: string | null;
  created_at: string | null;
}

export const fetchPrivacy = () => api<PrivacyState>("/api/org/privacy");

/**
 * Копия данных организации.
 *
 * Сервер отдаёт файл (`Content-Disposition`), но здесь мы забираем JSON и
 * сохраняем его сами: так запрос идёт через общий `api` с теми же заголовками
 * входа, и не нужно дублировать авторизацию ради скачивания.
 */
export const fetchOrgExport = () =>
  api<Record<string, unknown>>("/api/org/export");

export const requestOrgDeletion = (confirm: string) =>
  api<DeletionState>("/api/org", {
    method: "DELETE",
    body: JSON.stringify({ confirm }),
  });

export const cancelOrgDeletion = () =>
  api<DeletionState>("/api/org/restore", { method: "POST" });

export const fetchAudit = (limit = 20) =>
  api<AuditEvent[]>(`/api/org/audit?limit=${limit}`);

/**
 * Ротация ключа ссылок организации (S-10/S-11).
 *
 * Меняет только ключ этого клиента: чужие календари и фото не затрагиваются.
 * `previous_valid_until` — до какой даты принимаются уже выданные ссылки.
 */
export interface LinksRotated {
  rotated_at: string;
  previous_valid_until: string;
}

export const rotateOrgLinks = () =>
  api<LinksRotated>("/api/org/links/rotate", { method: "POST" });

/** Скачать собранный экспорт как файл. Имя — код и дата, без ПДн. */
export function saveExportFile(slug: string, data: Record<string, unknown>): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  link.href = url;
  link.download = `org-${slug}-${stamp}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Ссылка на blob живёт до перезагрузки и держит память: отпускаем сразу
  // после клика, скачивание уже началось.
  URL.revokeObjectURL(url);
}
