import { getInitData } from "@/tg/webapp";

import { api, apiPublicUrl } from "./client";

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
  /** `null` — человек входит по почте, Telegram к аккаунту не привязан. */
  telegram_id: number | null;
  department_id: number | null;
  department_name: string | null;
  position: string | null;
  /** Плашка должность/звание («Разработчик», «Управляющий»). */
  badge: string | null;
  badge_emoji: string | null;
  role: "employee" | "aup" | "admin";
  experience: "new" | "experienced" | null;
  onboarding_state: "new" | "department" | "experience" | "training" | "done";
  /** «Учимся вместе»: обучение продолжается в рабочих сменах. */
  learning_mode: boolean;
  is_aup: boolean;
  is_admin: boolean;
  /** Прописанный доступ в админку: переживает смену собственной роли. */
  is_staff: boolean;
  is_active: boolean;
  /** Тестовый пул `[BOT]` — помечается в интерфейсе. */
  is_demo: boolean;
  /** Профиль открыт: коллеги видят активность и цифры в карточке. */
  profile_public: boolean;
  /** Показывать ли коллегам последний заход / последнее медиа. */
  show_last_seen: boolean;
  show_last_media: boolean;
  /** Руководство разрешает выключать эти галочки (иначе они заперты). */
  can_toggle_last_seen: boolean;
  can_toggle_last_media: boolean;
  /** Руководство обязало держать профиль открытым — тумблер заперт. */
  profile_locked: boolean;
  last_seen_at: string | null;
}

export interface HrDepartment {
  id: number;
  name: string;
  slug: string;
  emoji: string | null;
  sort_order: number;
}

/** `shift` — открытие зала (у официанта сначала выбор зала), `close` —
 * общее закрытие смены, `first_day` — первый рабочий день. */
export type ChecklistKind = "first_day" | "shift" | "close";

export interface HrHall {
  id: number;
  name: string;
  slug: string;
  sort_order: number;
}

/** Снимок к отчёту: ссылка уже подписана сервером и годится для `<img>`. */
export interface HrPhoto {
  id: number;
  url: string;
  width?: number | null;
  height?: number | null;
  created_at?: string | null;
}

export interface HrChecklistItem {
  id: number;
  title: string;
  description: string | null;
  requires_photo: boolean;
  is_mandatory: boolean;
  done: boolean;
  done_at: string | null;
  photo_file_id: string | null;
  /** Фото, загруженное в приложении (или подтянутое из Telegram). */
  photo_url?: string | null;
  note: string | null;
  /** Расписание по дням недели: CSV ISO-номеров, null — каждый день. */
  weekdays?: string | null;
  /** «по четвергам» — готовая подпись с сервера. */
  schedule_label?: string;
  /** Пункт действует сегодня; false — виден, но ждёт своего дня. */
  active?: boolean;
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
  /** Зал смены: у открытия его выбирает сотрудник, у закрытия его нет. */
  hall_id?: number | null;
  hall_name?: string | null;
  /** Сначала нужно выбрать зал — списка пунктов пока нет. */
  needs_hall?: boolean;
}

export type TaskStatus =
  | "new"
  | "accepted"
  | "in_progress"
  /** Сдано руководителю: работа ждёт приёмки. */
  | "on_review"
  /** Руководитель вернул на доработку. */
  | "rework"
  | "done"
  | "overdue"
  | "failed";

export type TaskMode = "one_of" | "each" | "parts";

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
  /** Агрегат по всем исполнителям — в групповом поручении это не «мой» статус. */
  status: TaskStatus;
  created_by_employee_id: number | null;
  created_at: string;
  done_at: string | null;
  is_overdue: boolean;
  /** Режим группового поручения: один за всех / каждый сам / части работы. */
  mode: TaskMode;
  /** Смена, на которую выдано поручение (null — без привязки). */
  shift_date: string | null;
  /** Поручение с проверкой: «Выполнено» отправляет работу руководителю. */
  requires_review: boolean;
  /** Мой личный статус: что сделал именно я. */
  my_status: TaskStatus | null;
  /** Моя часть работы — только в режиме `parts`. */
  my_part: string | null;
  progress_done: number;
  progress_total: number;
  /** Расписание поручения по дням недели (null — каждый день). */
  weekdays?: string | null;
  schedule_label?: string;
  active_today?: boolean;
  /** Фотоотчёты: превью показываются прямо в карточке. */
  photos?: HrPhoto[];
}

export const TASK_MODE_LABEL: Record<TaskMode, string> = {
  one_of: "один за всех",
  each: "каждый сам",
  parts: "части работы",
};

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
  /** VISUAL_AUDIT P1.8: тестовый пул `[BOT]`. Старый бэкенд поля не шлёт —
   * тогда фронтенд падает обратно на префикс в имени. */
  is_demo?: boolean;
}

export interface HrFeed {
  scope: "self" | "department" | "all";
  can_filter: boolean;
  items: HrFeedItem[];
}

// --- Профиль и онбординг ---

export const fetchEmployee = () => api<HrEmployee>("/api/me/employee");

/** Открыть или закрыть свой профиль для коллег. */
export const setProfileVisibility = (isPublic: boolean) =>
  api<HrEmployee>("/api/me/profile-visibility", {
    method: "POST",
    body: JSON.stringify({ is_public: isPublic }),
  });

/**
 * Личные галочки карточки: показывать ли последний заход и последнее медиа.
 *
 * Сервер может не принять `false` — если руководство запретило скрывать, он
 * вернёт фактическое состояние, и UI покажет именно его.
 */
export const setProfilePrivacy = (body: {
  show_last_seen?: boolean;
  show_last_media?: boolean;
}) =>
  api<HrEmployee>("/api/me/privacy", {
    method: "POST",
    body: JSON.stringify(body),
  });

// --- Карточка коллеги -------------------------------------------------------

export interface HrProfileActivity {
  at: string;
  kind: string;
  text: string;
  ref_id: number | null;
}

/**
 * Карточка коллеги: кто он и что делал.
 *
 * Цифры и активность приходят только при `can_view`: закрытый профиль отдаёт
 * имя, отдел и плашку — они и так видны в ленте.
 */
export interface HrProfileMedia {
  id: number;
  url: string;
  at: string;
  caption: string;
  source: "task" | "checklist";
}

export interface HrProfileCard {
  employee_id: number;
  display_name: string;
  department_id: number | null;
  department_name: string | null;
  position: string | null;
  badge: string | null;
  badge_emoji: string | null;
  role: "employee" | "aup" | "admin";
  role_label: string;
  is_demo: boolean;
  is_self: boolean;
  can_manage: boolean;
  profile_open: boolean;
  can_view: boolean;
  show_last_seen: boolean;
  show_last_media: boolean;
  can_toggle_last_seen: boolean;
  can_toggle_last_media: boolean;
  last_seen_at: string | null;
  last_media: HrProfileMedia | null;
  xp: number;
  rank_title: string;
  rank_emoji: string;
  week_xp: number;
  week_place: number | null;
  week_total: number;
  checklist_items: number;
  tasks_done: number;
  shifts_done: number;
  activity: HrProfileActivity[];
}

export const fetchEmployeeCard = (employeeId: number) =>
  api<HrProfileCard>(`/api/employees/${employeeId}/card`);

export const submitOnboarding = (body: {
  department_id?: number | null;
  experience?: "new" | "experienced" | null;
  /** «Я уже запомнил»: закрыть знакомство без уроков. */
  finish?: boolean;
  /** Выбор режима на следующие смены: «Повторим вместе» / обычный режим. */
  learning_mode?: boolean;
}) =>
  api<HrEmployee>("/api/me/onboarding", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const fetchDepartments = () => api<HrDepartment[]>("/api/departments");

// --- Дашборд подразделения --------------------------------------------------

export interface DepartmentPerson {
  employee_id: number;
  display_name: string;
  badge: string | null;
  badge_emoji: string | null;
  position: string | null;
  role: "employee" | "aup" | "admin";
  is_demo: boolean;
  is_self: boolean;
  shift_status:
    | "planned"
    | "worked"
    | "sick"
    | "absent"
    | "dayoff"
    | "vacation"
    | null;
  checklist_done: number;
  checklist_total: number;
  tasks_open: number;
  tasks_overdue: number;
  last_seen_at: string | null;
  profile_public: boolean;
}

export interface DepartmentOverview {
  department_id: number;
  department_name: string;
  department_emoji: string | null;
  can_manage: boolean;
  show_presence: boolean;
  on_shift: number;
  overdue: number;
  people: DepartmentPerson[];
}

export const fetchDepartmentOverview = (departmentId: number) =>
  api<DepartmentOverview>(`/api/departments/${departmentId}/overview`);

// --- Настройка организации (мастер руководителя) ---------------------------

export type OrgProfileVisibility = "colleagues" | "managers" | "all_open";

export interface OrgSetup {
  done: boolean;
  industry: string;
  headcount: string;
  departments: string[];
  sections: string[];
  profile_visibility: OrgProfileVisibility;
  cross_department_watch: boolean;
  allow_hide_last_seen: boolean;
  allow_hide_media: boolean;
  presets: { name: string; emoji: string }[];
  can_edit: boolean;
}

export interface OrgSetupPatch {
  industry?: string;
  headcount?: string;
  departments?: string[];
  create_departments?: boolean;
  sections?: string[];
  profile_visibility?: OrgProfileVisibility;
  cross_department_watch?: boolean;
  allow_hide_last_seen?: boolean;
  allow_hide_media?: boolean;
  done?: boolean;
}

export const fetchOrgSetup = () => api<OrgSetup>("/api/org-setup");

export const saveOrgSetup = (body: OrgSetupPatch) =>
  api<OrgSetup>("/api/org-setup", {
    method: "POST",
    body: JSON.stringify(body),
  });

// --- Обучение пользованию приложением (этап онбординга) ---

export interface HrTrainingLesson {
  code: string;
  title: string;
  emoji: string;
  minutes: number;
  summary: string;
  steps: string[];
  done: boolean;
  /** Уровень программы: 1 — знакомство, 2 — задачи, 3 — самому. */
  level: number;
}

export interface HrTrainingLevel {
  level: number;
  title: string;
  hint: string;
  done: number;
  total: number;
}

export interface HrTraining {
  lessons: HrTrainingLesson[];
  levels: HrTrainingLevel[];
  done: number;
  total: number;
  percent: number;
  complete: boolean;
  onboarding_state: HrEmployee["onboarding_state"];
  next_code: string | null;
  /** Сегодняшняя смена по расписанию обучения (учебная / обычная). */
  today_training: boolean;
  /** Ставка: полная или частичная. */
  rate_type: "full" | "partial";
}

export const fetchTraining = () => api<HrTraining>("/api/me/training");

export const completeTrainingLesson = (code: string) =>
  api<HrTraining>(`/api/me/training/${encodeURIComponent(code)}`, {
    method: "POST",
  });

/** Сбросить свой курс и пройти его заново (отдел и опыт остаются). */
export const resetTraining = () =>
  api<HrTraining>("/api/me/training/reset", { method: "POST" });

// --- Чек-лист смены ---

export const fetchChecklist = (
  kind: ChecklistKind = "shift",
  shiftDate?: string,
) => {
  const params = new URLSearchParams({ kind });
  if (shiftDate) params.set("shift_date", shiftDate);
  return api<HrChecklist>(`/api/checklist?${params.toString()}`);
};

/** Активные залы ресторана (для выбора перед чек-листом открытия). */
export const fetchHalls = () => api<HrHall[]>("/api/halls");

/** Запомнить зал на сегодня и получить чек-лист этого зала. */
export const chooseHall = (hallId: number) =>
  api<HrChecklist>("/api/checklist/hall", {
    method: "POST",
    body: JSON.stringify({ hall_id: hallId }),
  });

export const completeChecklistItem = (body: {
  item_id: number;
  photo_file_id?: string | null;
  /** ID снимка, загруженного в приложении (`POST /api/media`). */
  media_id?: number | null;
  note?: string | null;
}) =>
  api<HrChecklist>("/api/checklist/complete", {
    method: "POST",
    body: JSON.stringify(body),
  });

// --- Поручения ---

export const fetchTasks = (includeClosed = false, shiftDate?: string) => {
  const params = new URLSearchParams({
    include_closed: includeClosed ? "true" : "false",
  });
  if (shiftDate) params.set("shift_date", shiftDate);
  return api<HrTask[]>(`/api/tasks?${params.toString()}`);
};

export type TaskAction = "accept" | "start" | "done";

/**
 * Мой статус поручения: в групповом режиме агрегат не отвечает «сделал ли я».
 *
 * Вынесено из экранов, потому что один и тот же счёт нужен в трёх местах:
 * «Мои задачи», рельс сводки и бейдж на вкладке. Разъехавшиеся правила
 * (например, `on_review`, посчитанный закрытым) дали бы разные числа на одном
 * экране.
 */
export function ownTaskStatus(task: HrTask): TaskStatus {
  return task.my_status ?? task.status;
}

/**
 * Закрыта ли задача для меня. `on_review` — ещё нет: работа сдана, но ждёт
 * приёмки, значит висит на сотруднике.
 */
export function isTaskClosedForMe(task: HrTask): boolean {
  const status = ownTaskStatus(task);
  return status === "done" || status === "failed";
}

/** Счёт для бейджа: сколько поручений открыто и сколько из них просрочено. */
export function countOpenTasks(tasks: HrTask[]): {
  open: number;
  overdue: number;
} {
  const open = tasks.filter((task) => !isTaskClosedForMe(task));
  return { open: open.length, overdue: open.filter((t) => t.is_overdue).length };
}

/** Приёмка работы руководителем: принять или вернуть на доработку. */
export const reviewTask = (
  taskId: number,
  body: { approve: boolean; employee_id?: number | null; comment?: string | null },
) =>
  api<HrTask>(`/api/tasks/${taskId}/review`, {
    method: "POST",
    body: JSON.stringify(body),
  });

/** Очередь приёмки: поручения, которые сдали исполнители. */
export const fetchReviewQueue = () => api<HrTask[]>("/api/tasks/review-queue");

// --- Тестовый пул `[BOT]` (админ) ---
//
// Заводим симуляторов работы, прячем их следы ОДНИМ тумблером или сносим их
// совсем. Ручек две с половиной сознательно: видимость (обратимо), очистка
// активности (не задевает людей) и полное удаление (люди + их `users`).

export interface HrDemoEmployee {
  employee_id: number;
  /** `null` — человек входит по почте, Telegram не привязан. */
  telegram_id: number | null;
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

/**
 * Фотоотчёт снимком из приложения: сначала `POST /api/media`, потом связать
 * с поручением. Отдельная ручка не нужна — сервер различает `media_id`.
 */
export const attachTaskPhoto = (taskId: number, mediaId: number) =>
  api<HrTask>(`/api/tasks/${taskId}/photo`, {
    method: "POST",
    body: JSON.stringify({ media_id: mediaId }),
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
    /** Язык текста записи: его собирает сервер, а не интерфейс. */
    lang?: "ru" | "en";
  } = {},
) => {
  const params = new URLSearchParams();
  if (opts.employeeId) params.set("employee_id", String(opts.employeeId));
  if (opts.departmentId) params.set("department_id", String(opts.departmentId));
  if (opts.kinds?.length) params.set("kinds", opts.kinds.join(","));
  if (opts.lang) params.set("lang", opts.lang);
  params.set("limit", String(opts.limit ?? 50));
  return api<HrFeed>(`/api/feed?${params.toString()}`);
};

export interface HrFeedFilterEmployee {
  id: number;
  display_name: string;
  /** Должность: в одном отделе бывает два одинаковых имени. */
  position: string | null;
  /** Плашка владельца («Разработчик», «Управляющий») — если должности нет. */
  badge: string | null;
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
  /** `null` — человек входит по почте, Telegram не привязан. */
  telegram_id: number | null;
  department_id: number | null;
  department_name: string | null;
  department_emoji: string | null;
  position: string | null;
  badge: string | null;
  badge_emoji: string | null;
  role: "employee" | "aup" | "admin";
  experience: string | null;
  onboarding_state: string;
  is_active: boolean;
  is_demo: boolean;
}

export interface HrAdminTaskAssignment {
  employee_id: number;
  display_name: string;
  status: TaskStatus;
  part: string | null;
  done_at: string | null;
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
  mode: TaskMode;
  shift_date: string | null;
  /** Проверка руководителем: работа уходит в `on_review`. */
  requires_review: boolean;
  progress_done: number;
  progress_total: number;
  assignments: HrAdminTaskAssignment[];
  /** Фотоотчёты — руководитель видит их при приёмке работы. */
  photos?: HrPhoto[];
  /** Расписание по дням недели: «по четвергам» (null — без расписания). */
  weekdays?: string | null;
  schedule_label?: string;
}

export interface HrSettings {
  reminders_enabled: boolean;
  remind_before_minutes: number;
  escalation_enabled: boolean;
  /** Вторая ступень: молчание руководителя дольше порога — пинг админам. */
  escalation_second_enabled: boolean;
  escalation_second_hours: number;
  /** Повторять пинг админам в каждой смене, пока задача висит. */
  escalation_second_repeat: boolean;
  tick_minutes: number;
  /** Один тумблер тестового пула `[BOT]`. */
  demo_visible: boolean;
  /** Рабочие часы ресторана (HH:MM) — на них равняются смены и уведомления. */
  work_open: string;
  work_close: string;
  notify_only_work_hours: boolean;
  notify_lead_minutes: number;
  notify_tail_minutes: number;
  /** До какого момента глушим Telegram-алерты (ISO) или `null`. */
  muted_until: string | null;
  /** Можно ли слать прямо сейчас (расчёт по часам и мьюту). */
  notifications_allowed: boolean;
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

export const fetchAdminTasks = (shiftDate?: string) =>
  api<HrAdminTask[]>(
    `/api/admin/tasks${shiftDate ? `?shift_date=${shiftDate}` : ""}`,
  );

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
  /** Проверка руководителем: работа уходит в `on_review`. */
  requires_review?: boolean;
  /** Дни недели (1 — Пн … 7 — Вс): «каждый четверг». Пусто — без расписания. */
  weekdays?: number[] | null;
  /** Режим группового поручения и смена, на которую оно выдано. */
  mode?: TaskMode;
  shift_date?: string | null;
  /** Текст части каждому исполнителю (только для режима `parts`). */
  parts?: Record<number, string> | null;
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

// --------------------------------------------------------------------------
// KPI смены (опыт за работу, нейтральные звания, сотрудник недели)
// --------------------------------------------------------------------------

export interface HrKpiCounts {
  checklist_items: number;
  shifts_done: number;
  tasks_done: number;
  tasks_on_time: number;
}

export interface HrKpiRank {
  code: string;
  title: string;
  emoji: string;
  threshold: number;
}

export interface HrKpiRules {
  xp_checklist_item: number;
  xp_shift_done: number;
  xp_task: number;
  xp_on_time: number;
  min_xp_winner: number;
}

export interface HrKpiWinner {
  employee_id: number;
  display_name: string;
  department: string | null;
  xp: number;
  tasks_done: number;
}

export interface HrMyKpi {
  xp: number;
  rank: HrKpiRank;
  next_rank: HrKpiRank | null;
  left: number;
  percent: number;
  week_xp: number;
  week_counts: HrKpiCounts;
  week_place: number | null;
  week_total: number;
  employee_of_week: HrKpiWinner | null;
  rules: HrKpiRules;
}

export interface HrKpiLeaderRow {
  place: number;
  employee_id: number;
  display_name: string;
  department: string | null;
  xp: number;
  counts: HrKpiCounts;
}

export interface HrKpiAdmin {
  week_start: string;
  week_end: string;
  rules: HrKpiRules;
  leaderboard: HrKpiLeaderRow[];
  employee_of_week: HrKpiWinner | null;
}

/** Своя карточка опыта — открыта всем сотрудникам. */
export const fetchMyKpi = () => api<HrMyKpi>("/api/kpi");

/** Рейтинг недели и веса опыта — ручка руководителя. */
export const fetchKpiOverview = () => api<HrKpiAdmin>("/api/admin/kpi");

/** Правка весов: только администратор, частичное обновление. */
export const updateKpiRules = (body: Partial<HrKpiRules>) =>
  api<HrKpiRules>("/api/admin/kpi/rules", {
    method: "PUT",
    body: JSON.stringify(body),
  });

// --------------------------------------------------------------------------
// Кабинет управляющего: сводка по смене, роли, мьют уведомлений
// --------------------------------------------------------------------------

export interface HrDashboardEmployee {
  employee_id: number;
  display_name: string;
  /** `null` — человек входит по почте, Telegram не привязан. */
  telegram_id: number | null;
  department_id: number | null;
  department_name: string | null;
  department_emoji: string | null;
  /** Должность из HR-профиля; показывается компактно рядом с именем. */
  position: string | null;
  role: "employee" | "aup" | "admin";
  badge: string | null;
  badge_emoji: string | null;
  checklist_done: number;
  checklist_total: number;
  tasks_open: number;
  tasks_overdue: number;
  has_run: boolean;
  last_activity_at: string | null;
  status: "done" | "late" | "in_progress" | "idle";
}

export interface HrDashboardDepartment {
  department_id: number;
  name: string;
  emoji: string | null;
  employees: number;
  started: number;
  done: number;
  open_tasks: number;
  overdue_tasks: number;
  open_issues: number;
}

export interface HrDashboardAttention {
  kind: "overdue" | "issue" | "late_shift";
  severity: "high" | "medium";
  text: string;
  task_id: number | null;
  employee_id: number | null;
  department_id: number | null;
}

export interface HrDashboardActivity {
  at: string;
  kind: string;
  text: string;
  employee_id: number | null;
  display_name: string | null;
}

export interface HrDashboard {
  work_date: string;
  scope: "all" | "department";
  departments: HrDashboardDepartment[];
  employees: HrDashboardEmployee[];
  attention: HrDashboardAttention[];
  activity: HrDashboardActivity[];
  total_employees: number;
  shifts_started: number;
  shifts_done: number;
  tasks_open: number;
  tasks_overdue: number;
  open_issues: number;
}

/** Сводка смены. Область видимости считает сервер по роли. */
export const fetchDashboard = () => api<HrDashboard>("/api/admin/dashboard");

/** Сменить собственную роль (админ смотрит приложение глазами другой роли). */
export const switchMyRole = (role: HrEmployee["role"]) =>
  api<HrAdminEmployee>("/api/admin/me/role", {
    method: "POST",
    body: JSON.stringify({ role }),
  });

/** Мьют алертов: часы вперёд, `0` — снять. */
export const muteNotifications = (hours: number) =>
  api<HrSettings>("/api/admin/notifications/mute", {
    method: "POST",
    body: JSON.stringify({ hours }),
  });

// --------------------------------------------------------------------------
// База стандартов и проверка знаний
// --------------------------------------------------------------------------

/**
 * Стандарт в списке. Правильные ответы сервер наружу не отдаёт: оценка идёт
 * на сервере, иначе тест превращается в «подсмотри ключ в network».
 */
export type StandardCategory =
  | "dishes"
  | "equipment"
  | "safety"
  | "service"
  | "other";

export interface HrStandard {
  id: number;
  title: string;
  emoji: string | null;
  category: StandardCategory;
  summary: string | null;
  department_id: number | null;
  department_name: string | null;
  pass_percent: number;
  /** Обязательный стандарт попадает в пробелы отчёта смены. */
  is_required: boolean;
  is_active: boolean;
  questions_count: number;
  /** Сдал ли я этот тест хотя бы раз. */
  passed: boolean;
  /** Процент последней попытки. */
  last_percent: number | null;
}

export interface HrStandardQuestion {
  id: number;
  text: string;
  options: string[];
}

export interface HrStandardDetail extends HrStandard {
  body: string;
  questions: HrStandardQuestion[];
}

export interface HrStandardsResponse {
  items: HrStandard[];
  passed: number;
  total: number;
  attempts: number;
}

export interface HrCheckResult {
  standard_id: number;
  total: number;
  correct: number;
  percent: number;
  passed: boolean;
  pass_percent: number;
  at: string;
  /** Номера вопросов, где ответ неверный — по ним и стоит перечитать стандарт. */
  wrong_indexes: number[];
}

export const STANDARD_CATEGORY_LABEL: Record<StandardCategory, string> = {
  dishes: "блюда",
  equipment: "оборудование",
  safety: "безопасность",
  service: "сервис",
  other: "другое",
};

export const fetchStandards = () =>
  api<HrStandardsResponse>("/api/standards");

export const fetchStandard = (id: number) =>
  api<HrStandardDetail>(`/api/standards/${id}`);

/** Сдать тест. Ответы сверяются на сервере — клиент не знает ключа. */
export const submitStandardCheck = (id: number, answers: number[]) =>
  api<HrCheckResult>(`/api/standards/${id}/check`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  });

export interface StandardDraft {
  title: string;
  body: string;
  category: StandardCategory;
  emoji?: string | null;
  summary?: string | null;
  department_id?: number | null;
  pass_percent?: number;
  is_required?: boolean;
  questions: {
    text: string;
    options: string[];
    correct_index: number;
  }[];
}

/** Завести стандарт (руководитель/админ). */
export const createStandard = (body: StandardDraft) =>
  api<HrStandardDetail>("/api/admin/standards", {
    method: "POST",
    body: JSON.stringify(body),
  });

export interface StandardPatch {
  is_required?: boolean;
  is_active?: boolean;
  pass_percent?: number;
}

/** Отметить стандарт обязательным или снять — без переписывания текста. */
export const updateStandard = (id: number, patch: StandardPatch) =>
  api<HrStandard>(`/api/admin/standards/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

// --------------------------------------------------------------------------
// Отчёты смены и пробелы по стандартам
// --------------------------------------------------------------------------

export interface HrPersonRef {
  employee_id: number;
  display_name: string;
  department_id: number | null;
}

export interface HrStandardCoverage {
  standard_id: number;
  title: string;
  emoji: string | null;
  department_id: number | null;
  department_name: string | null;
  required: boolean;
  passed: number;
  total: number;
  /** Кто из отдела ещё не сдал — имена приходят с сервера. */
  missing: HrPersonRef[];
}

export interface HrDepartmentRow {
  department_id: number;
  name: string;
  emoji: string | null;
  employees: number;
  shifts_started: number;
  shifts_done: number;
  tasks_shift: number;
  tasks_done: number;
  tasks_on_review: number;
  tasks_overdue: number;
  issues_open: number;
  required_gaps: number;
}

export interface HrShiftReport {
  work_date: string;
  scope: "all" | "department";
  department_id: number | null;
  departments: HrDepartmentRow[];
  employees_total: number;
  shifts_started: number;
  shifts_done: number;
  tasks_shift: number;
  tasks_done: number;
  tasks_on_review: number;
  tasks_overdue: number;
  tasks_failed: number;
  tasks_open: number;
  issues_open: number;
  issues_new: number;
  standards: HrStandardCoverage[];
  required_gaps: number;
}

export interface ReportParams {
  /** Дата смены `YYYY-MM-DD`; без неё сервер берёт сегодня. */
  on?: string;
  department_id?: number | null;
}

function reportQuery(params: ReportParams): string {
  const qs = new URLSearchParams();
  if (params.on) qs.set("on", params.on);
  if (params.department_id != null) qs.set("department_id", String(params.department_id));
  const tail = qs.toString();
  return tail ? `?${tail}` : "";
}

/** Срез смены на дату: люди, чек-листы, поручения, проблемы и стандарты. */
export const fetchShiftReport = (params: ReportParams = {}) =>
  api<HrShiftReport>(`/api/admin/reports/shift${reportQuery(params)}`);

/** Пробелы по стандартам: кто не сдал инструкцию. */
export const fetchStandardGaps = (
  params: ReportParams & { required_only?: boolean } = {},
) => {
  const tail = reportQuery(params);
  const glue = tail ? "&" : "?";
  const required = params.required_only === false ? "false" : "true";
  return api<HrStandardCoverage[]>(
    `/api/admin/reports/standards${tail}${glue}required_only=${required}`,
  );
};

// --------------------------------------------------------------------------
// Сброс текущей работы (двойное подтверждение)
// --------------------------------------------------------------------------

export interface HrResetPreview {
  scope: string;
  is_admin: boolean;
  department_id: number | null;
  counts: Record<string, number>;
  notes: string[];
  /** Подписанный токен предпросмотра; без него execute не сработает. */
  token: string;
  expires_in_seconds: number;
}

/** Сухой счёт: что исчезнет. Ничего не удаляет. */
export const fetchResetPreview = () =>
  api<HrResetPreview>("/api/admin/reset/preview");

/** Второй шаг: удалить показанное. Слово подтверждения проверяет сервер. */
export const executeReset = (token: string, confirm: string) =>
  api<Record<string, number>>("/api/admin/reset/execute", {
    method: "POST",
    body: JSON.stringify({ token, confirm }),
  });

/**
 * Скачать CSV смены.
 *
 * `api()` не годится: он парсит JSON. Но и просто `<a href>` не сработает —
 * сервер проверяет подпись `initData` в заголовке. Поэтому тянем файл
 * запросом с `tma`-заголовком и отдаём браузеру blob. Имя файла сервер уже
 * положил в `Content-Disposition`; запасное имя — на случай, если WebView его
 * не отдал.
 */
export async function downloadShiftCsv(params: ReportParams = {}): Promise<string> {
  const url = apiPublicUrl(`/api/admin/reports/shift.csv${reportQuery(params)}`);
  const res = await fetch(url, {
    headers: { Authorization: `tma ${getInitData()}` },
  });
  if (!res.ok) {
    throw new Error(`csv_failed:${res.status}`);
  }
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const filename = match?.[1] ?? `shift-${params.on ?? "today"}.csv`;
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
  return filename;
}
