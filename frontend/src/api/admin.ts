import { api } from "./client";

export interface ChukhanWeight {
  user_id: number;
  telegram_id: number;
  display_name: string;
  weight: number;
}

export interface ChukhanWeek {
  id: number;
  week_start: string;
  user_id: number;
  posted_at: string | null;
  tg_message_id: number | null;
}

export interface ChukhanLeaderRow {
  user_id: number;
  count: number;
}

export const fetchWeights = () =>
  api<ChukhanWeight[]>("/api/admin/chukhan/weights");

export const updateWeight = (telegramId: number, weight: number) =>
  api<ChukhanWeight>(`/api/admin/chukhan/weights/${telegramId}`, {
    method: "PUT",
    body: JSON.stringify({ weight }),
  });

export const resetWeight = (telegramId: number) =>
  api<void>(`/api/admin/chukhan/weights/${telegramId}`, { method: "DELETE" });

export const forceReroll = () =>
  api<ChukhanWeek>("/api/admin/chukhan/reroll", { method: "POST" });

export const fetchChukhanHistory = () =>
  api<ChukhanWeek[]>("/api/admin/chukhan/history");

export const fetchChukhanLeaderboard = () =>
  api<ChukhanLeaderRow[]>("/api/chukhan/leaderboard");

export interface ScheduledJob {
  id: string;
  kind: "cron" | "interval" | "reminder";
  label: string;
  next_run_at: string | null;
  detail: string | null;
}

export const fetchScheduledJobs = () =>
  api<ScheduledJob[]>("/api/admin/jobs");

export const cancelScheduledJob = (jobId: string) =>
  api<void>(`/api/admin/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });

export interface RandomPhrasesSettings {
  enabled: boolean;
  count: number;
}

export const fetchRandomPhrases = () =>
  api<RandomPhrasesSettings>("/api/admin/random-phrases");

export const updateRandomPhrases = (body: RandomPhrasesSettings) =>
  api<RandomPhrasesSettings>("/api/admin/random-phrases", {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const triggerRandomPhrases = () =>
  api<{ status: string }>("/api/admin/random-phrases/run-now", { method: "POST" });

export interface RandomPhrasesPoolRow {
  user_id: number;
  display_name: string;
  chunks_count: number;
}

export interface RandomPhrasesPool {
  lookback_days: number;
  total_chunks: number;
  rows: RandomPhrasesPoolRow[];
}

export const fetchRandomPhrasesPool = () =>
  api<RandomPhrasesPool>("/api/admin/random-phrases/pool");

export interface AdminPoll {
  id: number;
  question: string;
  closes_at: string | null;
  created_at: string;
  tg_message_id: number | null;
  is_open: boolean;
}

export const fetchAdminPolls = () => api<AdminPoll[]>("/api/admin/polls");

export const closeAdminPoll = (pollId: number) =>
  api<void>(`/api/admin/polls/${pollId}/close`, { method: "POST" });

export const deleteAdminPoll = (pollId: number) =>
  api<void>(`/api/admin/polls/${pollId}`, { method: "DELETE" });

// --- A1: Loser reasons CRUD ---

export interface LoserReasons {
  reasons: string[];
}

export const fetchLoserReasons = () =>
  api<LoserReasons>("/api/admin/loser-reasons");

export const updateLoserReasons = (reasons: string[]) =>
  api<LoserReasons>("/api/admin/loser-reasons", {
    method: "PUT",
    body: JSON.stringify({ reasons }),
  });

// --- A2: Reminders tick ---

export interface RemindersSettings {
  tick_minutes: number;
}

export const fetchRemindersSettings = () =>
  api<RemindersSettings>("/api/admin/reminders");

export const updateRemindersSettings = (tick_minutes: number) =>
  api<RemindersSettings>("/api/admin/reminders", {
    method: "PUT",
    body: JSON.stringify({ tick_minutes }),
  });

// --- A3: Random phrases schedule ---

export type RPScheduleMode = "daily_n" | "weekly_n" | "fixed_times" | "random_interval";

export interface RPSchedule {
  mode: RPScheduleMode;
  param: Record<string, unknown>;
}

export const fetchRPSchedule = () =>
  api<RPSchedule>("/api/admin/random-phrases/schedule");

export const updateRPSchedule = (body: RPSchedule) =>
  api<RPSchedule>("/api/admin/random-phrases/schedule", {
    method: "PUT",
    body: JSON.stringify(body),
  });

// --- A4: Generator settings ---

export interface RPGenerator {
  count_min: number;
  count_max: number;
  lookback_days: number;
  collective_chance: number;
  user_chance: number;
}

export const fetchRPGenerator = () =>
  api<RPGenerator>("/api/admin/random-phrases/generator");

export const updateRPGenerator = (body: RPGenerator) =>
  api<RPGenerator>("/api/admin/random-phrases/generator", {
    method: "PUT",
    body: JSON.stringify(body),
  });

// --- A6: Auto-loser ---

export interface AutoLoserSettings {
  enabled: boolean;
  window_start_hour: number;
  window_end_hour: number;
  interval_hours: number;
}

export const fetchAutoLoser = () =>
  api<AutoLoserSettings>("/api/admin/autoloser");

export const updateAutoLoser = (body: AutoLoserSettings) =>
  api<AutoLoserSettings>("/api/admin/autoloser", {
    method: "PUT",
    body: JSON.stringify(body),
  });

// --- A7: Loser history ---

export interface LoserHistoryRow {
  id: number;
  rolled_at: string;
  loser_user_id: number;
  rolled_by: number;
  reason_text: string | null;
}

export const fetchLoserHistory = () =>
  api<LoserHistoryRow[]>("/api/admin/loser/history");

// --- BD2: Birthdays ---

export interface BirthdayRow {
  user_id: number;
  display_name: string;
  bday: string | null; // YYYY-MM-DD
  year_known: boolean;
  remind_month: boolean;
  remind_week: boolean;
  remind_day: boolean;
  remind_on_day: boolean;
  remind_hint_week: boolean;
}

export const fetchBirthdays = () =>
  api<BirthdayRow[]>("/api/admin/birthdays");

export const updateBirthdays = (items: Omit<BirthdayRow, "display_name">[]) =>
  api<BirthdayRow[]>("/api/admin/birthdays", {
    method: "PUT",
    body: JSON.stringify({ items }),
  });
