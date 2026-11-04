import { api } from "./client";

/**
 * Ключи API и вебхуки организации (B2B_PLATFORM_PLAN, шаг 6.1).
 *
 * Ключ и секрет вебхука сервер отдаёт ровно один раз: в базе лежат только
 * хеши. Поэтому создание возвращает `token`/`secret` отдельным полем, а
 * список — уже без них. Экран обязан показать значение сразу и не пытаться
 * «перезагрузить» его из списка.
 */
export interface ApiKeyRow {
  id: number;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreated {
  key: ApiKeyRow;
  token: string;
}

export interface WebhookRow {
  id: number;
  url: string;
  events: string[];
  is_active: boolean;
  created_at: string;
  last_attempt_at: string | null;
  last_status_code: number | null;
  failures: number;
}

export interface WebhookCreated {
  webhook: WebhookRow;
  secret: string;
}

export interface ImportRunRow {
  id: number;
  key_id: number;
  kind: string;
  filename: string | null;
  status: string;
  created: number;
  updated: number;
  skipped: number;
  errors: number;
  created_at: string;
}

export interface DeliveryRow {
  id: number;
  endpoint_id: number;
  event: string;
  status: string;
  attempts: number;
  response_code: number | null;
  error: string | null;
  created_at: string;
  delivered_at: string | null;
}

export const EVENT_LABELS: Record<string, string> = {
  "employee.created": "Новый сотрудник",
  "employee.updated": "Сотрудник изменён",
  "employee.deactivated": "Сотрудник уволен",
};

export const SCOPE_LABELS: Record<string, string> = {
  "people.read": "Люди",
  "schedule.read": "График",
  "menu.read": "Меню",
  "contacts.read": "Контакты (почта)",
  // Запись — отдельные права (шаг 6.2): ключ, который читает, не должен
  // молча создавать людей. Владелец видит это в списке ключа.
  "people.write": "Люди (запись)",
  "schedule.write": "График (запись)",
};

export const fetchApiKeys = () => api<ApiKeyRow[]>("/api/org/api-keys");

export const createApiKey = (name: string, scopes: string[]) =>
  api<ApiKeyCreated>("/api/org/api-keys", {
    method: "POST",
    body: JSON.stringify({ name, scopes }),
  });

export const revokeApiKey = (id: number) =>
  api<ApiKeyRow>(`/api/org/api-keys/${id}`, { method: "DELETE" });

export const fetchWebhooks = () => api<WebhookRow[]>("/api/org/webhooks");

export const createWebhook = (url: string, events: string[]) =>
  api<WebhookCreated>("/api/org/webhooks", {
    method: "POST",
    body: JSON.stringify({ url, events }),
  });

export const updateWebhook = (
  id: number,
  patch: { url?: string; events?: string[]; is_active?: boolean },
) =>
  api<WebhookRow>(`/api/org/webhooks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const deleteWebhook = (id: number) =>
  api<void>(`/api/org/webhooks/${id}`, { method: "DELETE" });

export const fetchDeliveries = (limit = 20) =>
  api<DeliveryRow[]>(`/api/org/webhooks/deliveries?limit=${limit}`);

export const fetchImportRuns = (limit = 10) =>
  api<ImportRunRow[]>(`/api/org/import-runs?limit=${limit}`);
