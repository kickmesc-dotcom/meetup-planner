import { api } from "./client";

/**
 * Приглашения в организацию (B2B_PLATFORM_PLAN, шаг 2.2).
 *
 * Ссылка отдаётся ровно один раз — в ответе на создание: сервер хранит только
 * SHA-256 от токена, восстановить его нельзя. Поэтому в списке `link` нет.
 */

export type OrgRole = "owner" | "manager" | "staff";

export const ORG_ROLE_LABELS: Record<OrgRole, string> = {
  owner: "Владелец",
  manager: "Управляющий",
  staff: "Сотрудник",
};

export const ORG_ROLES: OrgRole[] = ["staff", "manager", "owner"];

export interface OrgInvitation {
  id: number;
  email: string | null;
  role: OrgRole;
  created_at: string | null;
  expires_at: string;
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

export const createInvitation = (input: {
  email?: string | null;
  role: OrgRole;
  days: number;
}) =>
  api<OrgInvitation>("/api/org/invitations", {
    method: "POST",
    body: JSON.stringify({
      email: input.email?.trim() || null,
      role: input.role,
      days: input.days,
    }),
  });

export const revokeInvitation = (id: number) =>
  api<void>(`/api/org/invitations/${id}`, { method: "DELETE" });

/** Что за организация зовёт — доступно до входа, токен и есть пропуск. */
export const previewInvitation = (token: string) =>
  api<InvitationPreview>(`/api/invitations/${encodeURIComponent(token)}`);

export const acceptInvitation = (token: string) =>
  api<AcceptResult>(
    `/api/invitations/${encodeURIComponent(token)}/accept`,
    { method: "POST" },
  );
