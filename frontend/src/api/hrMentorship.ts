import { api } from "./client";

/**
 * Первая неделя новичка.
 *
 * Сервер отдаёт только тех, кто принят в последние две недели, — экран не
 * заменяет пул сотрудников, а отвечает на один вопрос: кого стоит спросить
 * сегодня. `at_risk` считает сервер: правило должно быть одним для всех
 * клиентов, иначе бот и мини-апп начнут спорить о том, кто «пропал».
 */

export interface HrTrainee {
  employee_id: number;
  name: string;
  position: string | null;
  department_id: number | null;
  department: string | null;
  hired_on: string;
  days_in_team: number;
  shifts_week: number;
  overdue_tasks: number;
  last_seen_at: string | null;
  mentor_employee_id: number | null;
  mentor_name: string | null;
  at_risk: boolean;
}

export interface HrTrainees {
  window_days: number;
  items: HrTrainee[];
}

export const fetchTrainees = (departmentId: number | null = null) =>
  api<HrTrainees>(
    `/api/admin/mentorship/trainees${
      departmentId != null ? `?department_id=${departmentId}` : ""
    }`,
  );

export const setTraineeMentor = (employeeId: number, mentorId: number | null) =>
  api<HrTrainee>(`/api/admin/mentorship/trainees/${employeeId}/mentor`, {
    method: "PATCH",
    body: JSON.stringify({ mentor_employee_id: mentorId }),
  });
