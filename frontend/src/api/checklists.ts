import { api } from "@/api/client";

/**
 * Админский контур чек-листов: залы и шаблоны с пунктами.
 *
 * Отдельный модуль от `hr.ts`: это правка регламента управляющим, а не
 * прохождение смены сотрудником (`routes_hr_admin.py`).
 */

export type AdminChecklistKind = "shift" | "close" | "first_day";

export const KIND_LABEL: Record<AdminChecklistKind, string> = {
  shift: "Открытие зала",
  close: "Закрытие смены",
  first_day: "Первый день",
};

export interface AdminHall {
  id: number;
  name: string;
  slug: string;
  is_active: boolean;
  sort_order: number;
}

export interface AdminChecklistItem {
  id: number;
  template_id: number;
  title: string;
  description: string | null;
  requires_photo: boolean;
  is_mandatory: boolean;
  condition_position: string | null;
  /** Дни недели, в которые пункт действует: "1,4" (Пн и Чт), null — всегда. */
  weekdays: string | null;
  /** «по четвергам» — подпись считает сервер. */
  schedule_label?: string;
  sort_order: number;
}

export interface AdminChecklistTemplate {
  id: number;
  department_id: number;
  hall_id: number | null;
  title: string;
  kind: AdminChecklistKind;
  is_active: boolean;
  sort_order: number;
  items: AdminChecklistItem[];
}

export interface ChecklistItemInput {
  title: string;
  description?: string | null;
  requires_photo?: boolean;
  is_mandatory?: boolean;
  /** ISO-дни недели: 1 — Пн … 7 — Вс. Пустой список — каждый день. */
  weekdays?: number[];
  sort_order?: number;
}

// --- Залы -------------------------------------------------------------------

export const fetchAdminHalls = () => api<AdminHall[]>("/api/admin/halls");

export const createAdminHall = (name: string) =>
  api<AdminHall>("/api/admin/halls", {
    method: "POST",
    body: JSON.stringify({ name }),
  });

export const patchAdminHall = (
  id: number,
  body: { name?: string; is_active?: boolean; sort_order?: number },
) =>
  api<AdminHall>(`/api/admin/halls/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

// --- Шаблоны ----------------------------------------------------------------

export const fetchAdminChecklists = () =>
  api<AdminChecklistTemplate[]>("/api/admin/checklists");

export const createAdminChecklist = (body: {
  department_id: number;
  title: string;
  kind: AdminChecklistKind;
  hall_id?: number | null;
}) =>
  api<AdminChecklistTemplate>("/api/admin/checklists", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const patchAdminChecklist = (
  id: number,
  body: {
    title?: string;
    kind?: AdminChecklistKind;
    is_active?: boolean;
    sort_order?: number;
    hall_id?: number | null;
    /** Без флага `hall_id` не меняется — так можно снять привязку к залу. */
    hall_set?: boolean;
  },
) =>
  api<AdminChecklistTemplate>(`/api/admin/checklists/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const createChecklistItem = (
  templateId: number,
  body: ChecklistItemInput,
) =>
  api<AdminChecklistItem>(`/api/admin/checklists/${templateId}/items`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const patchChecklistItem = (
  itemId: number,
  body: Partial<ChecklistItemInput>,
) =>
  api<AdminChecklistItem>(`/api/admin/checklist-items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteChecklistItem = (itemId: number) =>
  api<void>(`/api/admin/checklist-items/${itemId}`, { method: "DELETE" });
