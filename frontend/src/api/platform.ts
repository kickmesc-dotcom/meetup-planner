import { api } from "./client";

/**
 * Админка платформы (B2B_PLATFORM_PLAN, шаг 4.3).
 *
 * Это не кабинет клиента: здесь список всех организаций, их тарифы, блокировки
 * и подтверждение оплаты. Доступ есть только у владельцев продукта — сервер
 * проверяет Telegram-id, а не роль в организации, поэтому «спрятать раздел на
 * фронте» не является защитой.
 */

export interface PlatformMe {
  is_platform_admin: boolean;
}

export interface PlatformPlan {
  code: string;
  title: string;
  seats: number;
  branches: number;
  price_month: number;
  price_year: number;
}

export interface PlatformOrg {
  id: number;
  slug: string;
  name: string;
  industry: string;
  is_active: boolean;
  plan: string;
  plan_title: string;
  seats_used: number;
  seats_limit: number;
  branches_used: number;
  branches_limit: number;
  trial_ends_at: string | null;
  plan_ends_at: string | null;
  trial_expired: boolean;
  subscription_expired: boolean;
  created_at: string | null;
}

export interface PlatformOrgs {
  items: PlatformOrg[];
  total: number;
}

export interface PlatformInvoice {
  id: number;
  org_id: number;
  org_name: string;
  number: string;
  plan: string;
  plan_title: string;
  period: string;
  amount: number;
  currency: string;
  status: string;
  created_at: string | null;
  expires_at: string;
  paid_at: string | null;
  period_start: string | null;
  period_end: string | null;
}

export interface PlatformInvoices {
  items: PlatformInvoice[];
  total: number;
  awaiting: number;
}

export interface PlatformSummary {
  organizations: number;
  active: number;
  on_trial: number;
  expired: number;
  awaiting_invoices: number;
  unpaid_amount: number;
  plans: PlatformPlan[];
}

export const fetchPlatformMe = () => api<PlatformMe>("/api/platform/me");

/** Сводка по всем клиентам. Только владельцу продукта. */
export const fetchPlatformSummary = () =>
  api<PlatformSummary>("/api/platform/summary");

export const fetchPlatformOrgs = (query: string) =>
  api<PlatformOrgs>(`/api/platform/orgs?q=${encodeURIComponent(query)}`);

/**
 * Сменить тариф или заблокировать клиента.
 *
 * `plan_ends_at: ""` снимает срок (бессрочный договор); `null`/отсутствие поля
 * срок не трогает — иначе любая правка тарифа стирала бы оплаченное время.
 */
export const patchPlatformOrg = (
  id: number,
  body: {
    plan?: string;
    plan_ends_at?: string;
    trial_ends_at?: string;
    is_active?: boolean;
  },
) =>
  api<PlatformOrg>(`/api/platform/orgs/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const fetchPlatformInvoices = (status = "") =>
  api<PlatformInvoices>(
    `/api/platform/invoices${status ? `?status=${encodeURIComponent(status)}` : ""}`,
  );

/** Подтвердить оплату: единственный путь, которым подписка продлевается. */
export const confirmPlatformInvoice = (id: number) =>
  api<PlatformInvoice>(`/api/platform/invoices/${id}/confirm`, {
    method: "POST",
  });

export const cancelPlatformInvoice = (id: number) =>
  api<PlatformInvoice>(`/api/platform/invoices/${id}/cancel`, {
    method: "POST",
  });
