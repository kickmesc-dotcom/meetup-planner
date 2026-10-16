import { api } from "./client";

/**
 * SemiTaskBot: типы и вызовы HR-ядра.
 *
 * Всё, что относится к рабочим экранам (сотрудник, чек-лист, поручения, ссылки,
 * обратная связь, лента), собрано здесь — по образцу `api/birthdays.ts`.
 * Права проверяет СЕРВЕР: фронт лишь прячет то, что бэкенд всё равно отклонит,
 * поэтому `can_filter`/`scope` приходят с сервера, а не вычисляются на клиенте.
 */

export interface HrEmployee {
  id: number;
  user_id: number;
  display_name: string;
  telegram_id: number;
  department_id: number | null;
  department_name: string | null;
  position: string | null;
  /** Плашка должность/звание («Разработчик», «Управляющий»). */
  badge: string | null;
  badge_emoji: string | null;
  role: "employee" | "aup" | "admin";
  experience: "new" | "experienced" | null;
  onboarding_state: "new" | "department" | "experience" | "done";
  is_aup: boolean;
  is_admin: boolean;
  is_active: boolean;
  /** Тестовый пул `[BOT]` — помечается в интерфейсе. */
  is_demo: boolean;
}

export interface HrDepartment {
  id: number;
  name: string;
  slug: string;
  emoji: string | null;
  sort_order: number;
}

export type ChecklistKind = "first_day" | "shift";

export interface HrChecklistItem {
  id: number;
  title: string;
  description: string | null;
  requires_photo: boolean;
  is_mandatory: boolean;
  done: boolean;
  done_at: string | null;
  photo_file_id: string | null;
  note: string | null;
}

export interface HrChecklist {
  run_id: number | null;
  template_id: number | null;
  template_title: string | null;
  kind: ChecklistKind;
  shift_date: string;
  status: "in_progress" | "done";
  done: number;
  total: number;
  progress_text: string;
  items: HrChecklistItem[];
}

export type TaskStatus =
  "new" | "accepted" | "in_progress" | "done" | "overdue" | "failed";

export interface HrTask {
  id: number;
  title: string;
  description: string | null;
  expected_result: string | null;
  scope: "department" | "employee";
  department_id: number | null;
  assignee_employee_id: number | null;
  due_at: string | null;
  priority: "low" | "normal" | "high";
  requires_photo: boolean;
  comment: string | null;
  status: TaskStatus;
  created_by_employee_id: number | null;
  created_at: string;
  done_at: string | null;
  is_overdue: boolean;
}

export interface HrLink {
  id: number;
  title: string;
  url: string;
  emoji: string | null;
  department_id: number | null;
}

export type QuestionKind = "scale" | "choice" | "text";

export interface HrFeedbackQuestion {
  id: number;
  code: string;
  text: string;
  kind: QuestionKind;
  options: string[];
}

export interface HrFeedbackAnswer {
  question_id: number;
  value_scale?: number | null;
  value_choice?: string | null;
  value_text?: string | null;
}

export type FeedKind =
  | "checklist_done"
  | "checklist_item"
  | "task_created"
  | "task_status"
  | "task_photo"
  | "task_issue";

export interface HrFeedItem {
  at: string;
  kind: FeedKind;
  employee_id: number | null;
  user_id: number | null;
  display_name: string;
  department_id: number | null;
  text: string;
  ref_id: number | null;
  badge: string | null;
  badge_emoji: string | null;
}

export interface HrFeed {
  scope: "self" | "department" | "all";
  can_filter: boolean;
  items: HrFeedItem[];
}

// --- Профиль и онбординг ---

export const fetchEmployee = () => api<HrEmployee>("/api/me/employee");

export const submitOnboarding = (body: {
  department_id?: number | null;
  experience?: "new" | "experienced" | null;
}) =>
  api<HrEmployee>("/api/me/onboarding", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const fetchDepartments = () => api<HrDepartment[]>("/api/departments");

// --- Чек-лист смены ---

export const fetchChecklist = (
  kind: ChecklistKind = "shift",
  shiftDate?: string,
) => {
  const params = new URLSearchParams({ kind });
  if (shiftDate) params.set("shift_date", shiftDate);
  return api<HrChecklist>(`/api/checklist?${params.toString()}`);
};

export const completeChecklistItem = (body: {
  item_id: number;
  photo_file_id?: string | null;
  note?: string | null;
}) =>
  api<HrChecklist>("/api/checklist/complete", {
    method: "POST",
    body: JSON.stringify(body),
  });

// --- Поручения ---

export const fetchTasks = (includeClosed = false) =>
  api<HrTask[]>(
    `/api/tasks?include_closed=${includeClosed ? "true" : "false"}`,
  );

export type TaskAction = "accept" | "start" | "done";

// --- Тестовый пул `[BOT]` (админ) ---
//
// Заводим симуляторов работы, прячем их следы ОДНИМ тумблером или сносим их
// совсем. Ручек две с половиной сознательно: видимость (обратимо), очистка
// активности (не задевает людей) и полное удаление (люди + их `users`).

export interface HrDemoEmployee {
  employee_id: number;
  telegram_id: number;
  display_name: string;
  badge: string | null;
  badge_emoji: string | null;
  department_id: number | null;
  department_name: string | null;
  is_active: boolean;
}

export interface HrDemoState {
  visible: boolean;
  prefix: string;
  employees: HrDemoEmployee[];
  activity: {
    checklist_runs: number;
    tasks: number;
    feedback_answers: number;
  };
}

export const fetchDemoState = () => api<HrDemoState>("/api/admin/demo");

export const setDemoVisible = (visible: boolean) =>
  api<HrDemoState>("/api/admin/demo", {
    method: "PUT",
    body: JSON.stringify({ visible }),
  });

export const seedDemoPool = () =>
  api<HrDemoState>("/api/admin/demo/seed", { method: "POST" });

export const simulateDemo = (days = 3) =>
  api<Record<string, number>>("/api/admin/demo/simulate", {
    method: "POST",
    body: JSON.stringify({ days }),
  });

export const purgeDemo = (deleteEmployees: boolean) =>
  api<Record<string, number>>("/api/admin/demo/purge", {
    method: "POST",
    body: JSON.stringify({ delete_employees: deleteEmployees }),
  });

export const runTaskAction = (taskId: number, action: TaskAction) =>
  api<HrTask>(`/api/tasks/${taskId}/${action}`, { method: "POST" });

export const reportTaskIssue = (
  taskId: number,
  body: {
    reason_code?: string | null;
    comment?: string | null;
    eta_at?: string | null;
  },
) =>
  api<HrTask>(`/api/tasks/${taskId}/issue`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const sendTaskPhoto = (taskId: number, fileId: string) =>
  api<HrTask>(`/api/tasks/${taskId}/photo`, {
    method: "POST",
    body: JSON.stringify({ file_id: fileId }),
  });

// --- Ссылки и обратная связь ---

export const fetchLinks = () => api<HrLink[]>("/api/links");

export const fetchFeedbackQuestions = () =>
  api<HrFeedbackQuestion[]>("/api/feedback/questions");

export const submitFeedback = (body: {
  shift_date?: string | null;
  answers: HrFeedbackAnswer[];
}) =>
  api<HrFeedbackQuestion[]>("/api/feedback", {
    method: "POST",
    body: JSON.stringify(body),
  });

// --- Лента (видимость определяет сервер) ---

export const fetchHrFeed = (
  opts: {
    employeeId?: number | null;
    departmentId?: number | null;
    kinds?: FeedKind[];
    limit?: number;
  } = {},
) => {
  const params = new URLSearchParams();
  if (opts.employeeId) params.set("employee_id", String(opts.employeeId));
  if (opts.departmentId) params.set("department_id", String(opts.departmentId));
  if (opts.kinds?.length) params.set("kinds", opts.kinds.join(","));
  params.set("limit", String(opts.limit ?? 50));
  return api<HrFeed>(`/api/feed?${params.toString()}`);
};

export interface HrFeedFilterEmployee {
  id: number;
  display_name: string;
  department_id: number | null;
}

export interface HrFeedFilters {
  scope: "self" | "department" | "all";
  can_filter: boolean;
  kinds: FeedKind[];
  employees: HrFeedFilterEmployee[];
  departments: HrDepartment[];
}

/**
 * Списки для фильтров ленты. Отдельная ручка, а не админская: руководитель
 * подразделения не админ, но фильтровать своих людей ему можно. Состав списков
 * сервер считает тем же правилом, что и саму ленту.
 */
export const fetchFeedFilters = () => api<HrFeedFilters>("/api/feed/filters");

// --- Админский контур (поручения и правила) ---

export interface HrAdminEmployee {
  id: number;
  user_id: number;
  display_name: string;
  telegram_id: number;
  department_id: number | null;
  position: string | null;
  role: "employee" | "aup" | "admin";
  experience: string | null;
  onboarding_state: string;
  is_active: boolean;
}

export interface HrAdminTask {
  id: number;
  title: string;
  scope: "department" | "employee";
  department_id: number | null;
  assignee_employee_id: number | null;
  due_at: string | null;
  priority: string;
  requires_photo: boolean;
  status: TaskStatus;
  created_by_employee_id: number | null;
  created_at: string;
  done_at: string | null;
  is_overdue: boolean;
  assignee_ids: number[];
}

export interface HrSettings {
  reminders_enabled: boolean;
  remind_before_minutes: number;
  escalation_enabled: boolean;
  tick_minutes: number;
  /** Один тумблер тестового пула `[BOT]`. */
  demo_visible: boolean;
}

export const fetchHrSettings = () => api<HrSettings>("/api/admin/settings/hr");

export const updateHrSettings = (body: Partial<HrSettings>) =>
  api<HrSettings>("/api/admin/settings/hr", {
    method: "PUT",
    body: JSON.stringify(body),
  });

/** Скрытый блок личного прогресса (ачивки за работу). */
export interface HrAchievement {
  code: string;
  title: string;
  emoji: string;
  awarded_at: string;
}

export interface HrAchievementGoal {
  code: string;
  title: string;
  emoji: string;
  metric: string;
  threshold: number;
  done: number;
  left: number;
  text: string;
}

export interface HrAchievements {
  /** Показывать ли блок: сейчас его видят только руководитель и админ. */
  visible: boolean;
  awarded: HrAchievement[];
  stats: Record<string, number>;
  next_goals: HrAchievementGoal[];
  note: string;
}

/** Свои ачивки. Сервер сам решает, отдавать ли содержимое (`visible`). */
export const fetchAchievements = () =>
  api<HrAchievements>("/api/me/achievements");

/** Ачивки конкретного сотрудника — ручка руководителя. */
export const fetchEmployeeAchievements = (employeeId: number) =>
  api<HrAchievements>(`/api/admin/employees/${employeeId}/achievements`);

export const fetchAdminEmployees = () =>
  api<HrAdminEmployee[]>("/api/admin/employees");

export const fetchAdminTasks = () => api<HrAdminTask[]>("/api/admin/tasks");

export const createAdminTask = (body: {
  title: string;
  scope: "department" | "employee";
  department_id?: number | null;
  assignee_employee_id?: number | null;
  description?: string | null;
  expected_result?: string | null;
  due_at?: string | null;
  priority?: string;
  requires_photo?: boolean;
  comment?: string | null;
}) =>
  api<HrAdminTask>("/api/admin/tasks", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const setAdminTaskStatus = (
  taskId: number,
  status: TaskStatus,
  comment?: string,
) =>
  api<HrAdminTask>(`/api/admin/tasks/${taskId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status, comment }),
  });
