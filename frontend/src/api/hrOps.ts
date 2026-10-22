import { api } from "@/api/client";

/**
 * Админские операции: журнал событий, центр уведомлений и пул сотрудников.
 *
 * Отдельный модуль, а не приписка к `hr.ts`: это управляющий контур, а не
 * кабинет сотрудника, и живёт он по своим правилам (см. `routes_hr_ops_admin`).
 *
 * Здесь же ручное заведение по Telegram-ID и снапшоты состава: пул ID — самое
 * дорогое в базе, и потерять его вместе с удалённым профилем нельзя.
 */

// --- Журнал событий ---------------------------------------------------------

export interface HrJournalItem {
  at: string;
  kind: string;
  text: string;
  /** Строку написал планировщик (`auto_overdue`, `reminder_sent`). */
  is_system: boolean;
  task_id: number | null;
  task_title: string | null;
  employee_id: number | null;
  display_name: string | null;
}

export const fetchJournal = (limit = 100) =>
  api<{ items: HrJournalItem[] }>(`/api/admin/journal?limit=${limit}`);

// --- Центр уведомлений ------------------------------------------------------

export interface HrNotificationItem {
  id: number;
  kind: string;
  text: string;
  created_at: string;
  read_at: string | null;
  employee_id: number | null;
  user_id: number;
  display_name: string | null;
  department_name: string | null;
}

export interface HrPendingNotification {
  kind: "deadline" | "escalation";
  at: string;
  text: string;
  task_id: number;
  task_title: string;
  employee_id: number;
  display_name: string;
  /** Время сдвинули вручную, а не посчитал планировщик. */
  moved: boolean;
}

/** Напоминание, выключенное вручную (можно вернуть). */
export interface HrDisabledReminder {
  task_id: number;
  task_title: string;
  employee_id: number;
  display_name: string;
}

export interface HrNotificationsFeed {
  items: HrNotificationItem[];
  pending: HrPendingNotification[];
  /** До какого момента заглушены алерты в Telegram (null — не заглушено). */
  muted_until: string | null;
  scheduled_enabled: boolean;
  disabled: HrDisabledReminder[];
}

export const fetchNotificationsCenter = () =>
  api<HrNotificationsFeed>("/api/admin/notifications");

export const cancelNotification = (id: number) =>
  api<{ removed: boolean }>(`/api/admin/notifications/${id}/cancel`, {
    method: "POST",
  });

export const sendNotification = (employeeId: number, text: string) =>
  api<HrNotificationItem>("/api/admin/notifications/send", {
    method: "POST",
    body: JSON.stringify({ employee_id: employeeId, text }),
  });

/** Передвинуть напоминание по поручению на `minutes` вперёд. */
export const postponePendingNotification = (taskId: number, minutes: number) =>
  api<{ at: string }>(`/api/admin/notifications/pending/${taskId}/postpone`, {
    method: "POST",
    body: JSON.stringify({ minutes }),
  });

/** Выключить напоминание по поручению (вторая ступень живёт отдельно). */
export const skipPendingNotification = (taskId: number) =>
  api<{ skipped: boolean }>(`/api/admin/notifications/pending/${taskId}/skip`, {
    method: "POST",
  });

/** Вернуть напоминание к обычному расчёту планировщика. */
export const resetPendingNotification = (taskId: number) =>
  api<{ reset: boolean }>(`/api/admin/notifications/pending/${taskId}/reset`, {
    method: "POST",
  });

/** Мьют всех алертов: `hours = 0` снимает запрет. */
export const muteAllNotifications = (hours: number) =>
  api<{ muted_until: string | null }>("/api/admin/notifications/mute", {
    method: "POST",
    body: JSON.stringify({ hours }),
  });

// --- Пул сотрудников --------------------------------------------------------

export interface HrEmployeeCard {
  employee_id: number;
  user_id: number;
  /** Telegram-ID: по нему человека ищут и выдают права. */
  telegram_id: number;
  display_name: string;
  position: string | null;
  badge: string | null;
  badge_emoji: string | null;
  role: string;
  department_id: number | null;
  department_name: string | null;
  onboarding_state: string;
  learning_mode: boolean;
  is_demo: boolean;
  is_active: boolean;
  fired_at: string | null;
  purge_after: string | null;
  profile_public: boolean;
}

/** Роль человека в боте: от неё зависят лента, поручения и админка. */
export type HrRole = "employee" | "aup" | "admin";

export const ROLE_LABEL: Record<HrRole, string> = {
  employee: "Сотрудник",
  aup: "Руководитель",
  admin: "Администратор",
};

export interface HrEmployeesPool {
  items: HrEmployeeCard[];
  trash_days: number;
}

export const fetchEmployeesPool = () =>
  api<HrEmployeesPool>("/api/admin/employees-pool");

export const patchEmployee = (
  employeeId: number,
  body: {
    display_name?: string;
    position?: string;
    badge?: string;
    badge_emoji?: string;
    /** Роль: меняет только администратор (проверка на сервере). */
    role?: HrRole;
  },
) =>
  api<HrEmployeeCard>(`/api/admin/employees/${employeeId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

/** Найти человека по Telegram-ID — в том числе если он уже есть в пуле. */
export const findEmployeeByTelegramId = (telegramId: number) =>
  api<HrEmployeeCard>(
    `/api/admin/employees-pool/find?telegram_id=${encodeURIComponent(telegramId)}`,
  );

export const resetEmployeeProgress = (employeeId: number) =>
  api<HrEmployeeCard>(`/api/admin/employees/${employeeId}/reset-progress`, {
    method: "POST",
  });

/** Уволить: `trash` — корзина на 30 дней, `purge` — удалить сразу. */
export const fireEmployee = (employeeId: number, mode: "trash" | "purge") =>
  api<HrEmployeeCard>(`/api/admin/employees/${employeeId}/fire`, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });

export const restoreEmployee = (employeeId: number) =>
  api<HrEmployeeCard>(`/api/admin/employees/${employeeId}/restore`, {
    method: "POST",
  });

/** Завести человека по Telegram-ID, не дожидаясь его первого входа. */
export const addEmployeeByTelegramId = (body: {
  telegram_id: number;
  display_name?: string;
  department_id?: number;
  position?: string;
  badge?: string;
  role?: "employee" | "aup" | "admin";
}) =>
  api<HrEmployeeCard>("/api/admin/employees-pool/add", {
    method: "POST",
    body: JSON.stringify(body),
  });

// --- Снапшоты состава -------------------------------------------------------

export interface HrRosterSnapshot {
  id: number;
  label: string;
  kind: "manual" | "auto";
  /** Что сняло автоматический снимок: `fire:12`, `demo:purge`. */
  source: string;
  people_count: number;
  created_at: string;
}

export interface HrRosterPerson {
  telegram_id: number;
  display_name: string;
  department_name: string | null;
  position: string | null;
  role: string;
  is_demo: boolean;
}

export interface HrRosterRestoreResult {
  created: number;
  restored: number;
  skipped: number;
  /** Отделы из снимка, которых больше нет в базе. */
  departments_missing: string[];
}

export const fetchRosterSnapshots = () =>
  api<{ items: HrRosterSnapshot[]; max_snapshots: number }>(
    "/api/admin/roster-snapshots",
  );

export const createRosterSnapshot = (label?: string) =>
  api<{ snapshot: HrRosterSnapshot; people: HrRosterPerson[] }>(
    "/api/admin/roster-snapshots",
    { method: "POST", body: JSON.stringify({ label }) },
  );

export const restoreRosterSnapshot = (snapshotId: number) =>
  api<HrRosterRestoreResult>(
    `/api/admin/roster-snapshots/${snapshotId}/restore`,
    { method: "POST" },
  );

export const deleteRosterSnapshot = (snapshotId: number) =>
  api<{ removed: boolean }>(`/api/admin/roster-snapshots/${snapshotId}`, {
    method: "DELETE",
  });

/** Зачесть поручение выполненным за конкретного человека (ручное решение). */
export const forceTaskDone = (
  taskId: number,
  employeeId: number,
  comment?: string,
) =>
  api<{ id: number; status: string }>(
    `/api/admin/tasks/${taskId}/force-done`,
    {
      method: "POST",
      body: JSON.stringify({ employee_id: employeeId, comment }),
    },
  );
