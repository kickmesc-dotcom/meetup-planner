import { api } from "@/api/client";

/**
 * Расписание обучения новичков: учебные и обычные смены + ставка.
 *
 * Отдельный модуль, а не приписка к `hr.ts`: это управляющий контур, как
 * журнал и пул сотрудников (`api/hrOps.ts`).
 */

export type HrRateType = "full" | "partial";

export interface HrPlanDay {
  /** ISO-дата (`YYYY-MM-DD`). */
  day: string;
  is_training: boolean;
  /** День задан вручную, а не выведен из «первых N смен». */
  explicit: boolean;
  /** Статус смены в табеле (`null` — смены нет). */
  shift_status: string | null;
}

export interface HrEmployeePlan {
  employee_id: number;
  user_id: number;
  display_name: string;
  position: string | null;
  department_name: string | null;
  role: "employee" | "aup" | "admin";
  onboarding_state: "new" | "department" | "experience" | "training" | "done";
  learning_mode: boolean;
  rate_type: HrRateType;
  training_days: number;
  hire_date: string | null;
  /** В табеле есть смены — учебные считаются по факту, а не по календарю. */
  has_shifts: boolean;
  days: HrPlanDay[];
}

export interface HrTrainingPlan {
  start: string;
  days: number;
  rate_labels: Record<string, string>;
  items: HrEmployeePlan[];
}

export const fetchTrainingPlan = (days = 14) =>
  api<HrTrainingPlan>(`/api/admin/training-plan?days=${days}`);

export const patchTrainingPlan = (
  employeeId: number,
  body: { rate_type?: HrRateType; training_days?: number },
) =>
  api<HrEmployeePlan>(`/api/admin/training-plan/${employeeId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const setTrainingDay = (
  employeeId: number,
  day: string,
  isTraining: boolean,
) =>
  api<HrPlanDay>(`/api/admin/training-plan/${employeeId}/days/${day}`, {
    method: "PUT",
    body: JSON.stringify({ is_training: isTraining }),
  });

/** Вернуть день к правилу «первые N смен после найма». */
export const clearTrainingDay = (employeeId: number, day: string) =>
  api<{ cleared: boolean }>(
    `/api/admin/training-plan/${employeeId}/days/${day}`,
    { method: "DELETE" },
  );
