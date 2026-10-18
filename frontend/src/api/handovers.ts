import { api } from "./client";

/**
 * Передача смены: снимок открытых хвостов и подтверждение принимающим.
 *
 * Особенность контракта: `items` приходят и в списке (пустой массив), и в
 * деталях (полный снимок). Счётчик `items_count` есть всегда — по нему
 * рисуется строка списка, не подгружая каждую сдачу.
 */

export type HandoverStatus = "sent" | "accepted" | "rejected";
export type HandoverKind = "task" | "issue";

export const HANDOVER_STATUS_LABEL: Record<HandoverStatus, string> = {
  sent: "Ожидает",
  accepted: "Принята",
  rejected: "Возвращена",
};

export interface HrHandoverItem {
  id: number;
  kind: HandoverKind;
  ref_id: number | null;
  title: string;
  status: string;
  meta: string | null;
}

export interface HrHandover {
  id: number;
  status: HandoverStatus;
  shift_date: string;
  note: string | null;
  reject_reason: string | null;
  department_id: number | null;
  department_name: string | null;
  from_employee_id: number | null;
  from_name: string | null;
  to_employee_id: number | null;
  to_name: string | null;
  accepted_by_employee_id: number | null;
  accepted_by_name: string | null;
  created_at: string;
  accepted_at: string | null;
  items_count: number;
  can_accept: boolean;
  can_reject: boolean;
  items: HrHandoverItem[];
}

export interface HrHandoverSummary {
  incoming: number;
  outgoing: number;
  pending: number;
}

export interface HrHandovers {
  summary: HrHandoverSummary;
  items: HrHandover[];
}

export interface HrHandoverPreview {
  items: HrHandoverItem[];
  tasks: number;
  issues: number;
}

export type HandoverBox = "all" | "incoming" | "outgoing";

export const fetchHandovers = (box: HandoverBox = "all", limit = 50) =>
  api<HrHandovers>(`/api/handovers?box=${box}&limit=${limit}`);

export const fetchHandoverSummary = () =>
  api<HrHandoverSummary>("/api/handovers/summary");

export const fetchHandoverPreview = () =>
  api<HrHandoverPreview>("/api/handovers/preview");

export const fetchColleagues = () =>
  api<{ id: number; display_name: string }[]>("/api/handovers/colleagues");

export const fetchHandover = (id: number) =>
  api<HrHandover>(`/api/handovers/${id}`);

export const createHandover = (body: {
  to_employee_id: number;
  note?: string | null;
}) =>
  api<HrHandover>("/api/handovers", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const acceptHandover = (id: number, note?: string | null) =>
  api<HrHandover>(`/api/handovers/${id}/accept`, {
    method: "POST",
    body: JSON.stringify({ note: note ?? null }),
  });

export const rejectHandover = (id: number, reason: string) =>
  api<HrHandover>(`/api/handovers/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
