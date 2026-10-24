import { api } from "./client";

/**
 * Организации: приглашения, вход по коду и создание своей.
 *
 * Ручки `/api/invitations/*` не требуют организации — токен и есть пропуск.
 * Ручки `/api/org/*` работают от имени вошедшего человека: список клиентов
 * платформы наружу не отдаётся, вход возможен только по точному коду или
 * точному названию, которое человек получил от своего руководителя.
 */

export type OrgRole = "staff" | "manager" | "owner";

/** Роли от младшей к старшей: в форме приглашения первым стоит «сотрудник». */
export const ORG_ROLES: OrgRole[] = ["staff", "manager", "owner"];

/**
 * Подписи ролей. Русские ключи сознательно: экран приглашений показывает их
 * как есть, а перевод — задача `tx(...)` в месте показа, когда дойдёт очередь
 * этого экрана.
 */
export const ORG_ROLE_LABELS: Record<OrgRole, string> = {
  owner: "Владелец",
  manager: "Управляющий",
  staff: "Сотрудник",
};

export interface OrgInvitation {
  id: number;
  email: string | null;
  role: OrgRole;
  created_at: string | null;
  expires_at: string;
  /** Ссылка приходит только в ответе на создание: в базе лежит её хеш. */
  link?: string | null;
  mail_sent?: boolean;
}

export interface InvitationPreview {
  org_name: string;
  role: OrgRole;
  email: string | null;
  expires_at: string;
}

export interface AcceptResult {
  ok: boolean;
  org_id: number;
  org_name: string;
  role: OrgRole;
}

export const fetchInvitations = () =>
  api<OrgInvitation[]>("/api/org/invitations");

export const createInvitation = (body: {
  email: string | null;
  role: OrgRole;
  days: number;
}) =>
  api<OrgInvitation>("/api/org/invitations", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const revokeInvitation = (id: number) =>
  api<void>(`/api/org/invitations/${id}`, { method: "DELETE" });

export const previewInvitation = (token: string) =>
  api<InvitationPreview>(`/api/invitations/${encodeURIComponent(token)}`);

export const acceptInvitation = (token: string) =>
  api<AcceptResult>(`/api/invitations/${encodeURIComponent(token)}/accept`, {
    method: "POST",
  });

/**
 * Организация с точки зрения человека: имя, код и его роль.
 *
 * Код (`slug`) — тот самый «ID компании», который руководитель передаёт
 * сотруднику.
 */
export interface OrgInfo {
  id: number;
  slug: string;
  name: string;
  role: string;
}

/** Присоединиться по точному коду или названию. Роль при входе — `staff`. */
export const joinOrganization = (code: string) =>
  api<OrgInfo>("/api/org/join", {
    method: "POST",
    body: JSON.stringify({ code: code.trim() }),
  });

/** Завести свою организацию: человек сразу становится её владельцем. */
export const createOrganization = (name: string, industry: string) =>
  api<OrgInfo>("/api/org/create", {
    method: "POST",
    body: JSON.stringify({ name: name.trim(), industry }),
  });

/** Своя организация: имя и код для приглашений. */
export const fetchCurrentOrg = () => api<OrgInfo>("/api/org/current");
