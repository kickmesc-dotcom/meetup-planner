import { api } from "@/api/client";

/**
 * Табель смен.
 *
 * Сотрудник видит смены своего подразделения (read-only), управляющий и
 * разработчик — все отделы и могут править. Права проверяет сервер,
 * `can_edit` здесь — только чтобы не показывать лишние кнопки.
 */

export type ShiftStatus =
  | "planned"
  | "worked"
  | "sick"
  | "absent"
  | "dayoff"
  | "vacation";

export interface ShiftItem {
  id: number;
  employee_id: number;
  day: string;
  status: ShiftStatus;
  status_label: string;
  short: string;
  starts_at: string | null;
  ends_at: string | null;
  note: string | null;
  moved_from: string | null;
  /** Учебная смена по плану обучения (учитывает табель). */
  is_training: boolean;
}

export interface ShiftPerson {
  employee_id: number;
  display_name: string;
  position: string | null;
  department_id: number | null;
  department_name: string | null;
}

export interface ShiftStatusMeta {
  value: ShiftStatus;
  label: string;
  short: string;
}

export interface ShiftWeek {
  start: string;
  end: string;
  today: string;
  can_edit: boolean;
  statuses: ShiftStatusMeta[];
  departments: { id: number; name: string }[];
  people: ShiftPerson[];
  shifts: ShiftItem[];
}

export const fetchShiftWeek = (
  start: string,
  options: { days?: number; departmentId?: number | null } = {},
) =>
  api<ShiftWeek>(
    `/api/shifts?start=${start}&days=${options.days ?? 7}` +
      (options.departmentId ? `&department_id=${options.departmentId}` : ""),
  );

export interface ShiftInput {
  status: ShiftStatus;
  starts_at?: string | null;
  ends_at?: string | null;
  note?: string | null;
}

export const saveShift = (
  employeeId: number,
  day: string,
  body: ShiftInput,
) =>
  api<ShiftItem>(`/api/shifts/${employeeId}/${day}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const moveShift = (shiftId: number, day: string) =>
  api<ShiftItem>(`/api/shifts/${shiftId}/move`, {
    method: "POST",
    body: JSON.stringify({ day }),
  });

export const deleteShift = (shiftId: number) =>
  api<{ removed: boolean }>(`/api/shifts/${shiftId}`, { method: "DELETE" });
