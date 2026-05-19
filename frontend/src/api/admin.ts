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

// --- GHG6 AD6: Chukhan reasons CRUD (отдельные шаблоны фраз чухана) ---

export const fetchChukhanReasons = () =>
  api<LoserReasons>("/api/admin/chukhan-reasons");

export const updateChukhanReasons = (reasons: string[]) =>
  api<LoserReasons>("/api/admin/chukhan-reasons", {
    method: "PUT",
    body: JSON.stringify({ reasons }),
  });

// --- GHG6 AD5: Quick action — крутануть лоха из админки ---

export interface LoserRollNow {
  ok: boolean;
  loser_user_id: number | null;
  reason_text: string | null;
  error: string | null;
}

export const adminLoserRollNow = () =>
  api<LoserRollNow>("/api/admin/loser/roll-now", { method: "POST" });

// --- GHG6 AD4/AD8: Scheduled publications master-toggles ---

export interface ScheduledRemindersIO {
  enabled: boolean;
  tick_minutes: number;
}

export interface ScheduledLoserIO {
  enabled: boolean;
  per_day: number;
  window_start_hour: number;
  window_end_hour: number;
  interval_hours: number;
}

export interface ScheduledPhrasesIO {
  enabled: boolean;
  window_start: string;
  window_end: string;
}

export interface ScheduledAvatarsIO {
  enabled: boolean;
  per_day: number;
}

export interface ScheduledBirthdaysIO {
  alerts_enabled: boolean;
}

export interface ScheduledChukhanIO {
  weekday: number; // 0=Mon
  window_start: string;
  window_end: string;
}

export interface ScheduledSettingsIO {
  reminders: ScheduledRemindersIO;
  loser: ScheduledLoserIO;
  phrases: ScheduledPhrasesIO;
  avatars: ScheduledAvatarsIO;
  birthdays: ScheduledBirthdaysIO;
  chukhan: ScheduledChukhanIO;
}

export const fetchScheduledSettings = () =>
  api<ScheduledSettingsIO>("/api/admin/scheduled");

export const updateScheduledSettings = (body: ScheduledSettingsIO) =>
  api<ScheduledSettingsIO>("/api/admin/scheduled", {
    method: "PUT",
    body: JSON.stringify(body),
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

// --- GHG5 POLL-HOURS1: Time presets for polls ---

export interface PollPreset {
  start: string; // HH:MM
  end: string;   // HH:MM
  label?: string | null;
}

export const fetchPollPresetsAdmin = () =>
  api<{ presets: PollPreset[] }>("/api/admin/poll-presets");

export const updatePollPresets = (presets: PollPreset[]) =>
  api<{ presets: PollPreset[] }>("/api/admin/poll-presets", {
    method: "PUT",
    body: JSON.stringify({ presets }),
  });

// Public — для AutoPickSheet / PollSheet
export const fetchPollPresetsPublic = () =>
  api<PollPreset[]>("/api/poll-presets");

// --- GHG5 P2: Smart Proxy ---

export type ProxyMode = "always_on" | "always_off" | "auto_fallback";
export type ProxyType = "mtproto" | "socks5" | "http";

export interface ProxyEntry {
  id: number;
  server: string;
  port: number;
  type: ProxyType;
  secret: string | null;
  enabled: boolean;
  fail_count: number;
  last_ok_at: string | null;
  last_fail_at: string | null;
  dead_until: string | null;
}

export const fetchProxyMode = () =>
  api<{ mode: ProxyMode }>("/api/admin/proxy/mode");

export const updateProxyMode = (mode: ProxyMode) =>
  api<{ mode: ProxyMode }>("/api/admin/proxy/mode", {
    method: "PUT",
    body: JSON.stringify({ mode }),
  });

export const fetchProxies = () => api<ProxyEntry[]>("/api/admin/proxy");

export const createProxy = (body: {
  server: string;
  port: number;
  type: ProxyType;
  secret?: string | null;
  enabled?: boolean;
}) =>
  api<ProxyEntry>("/api/admin/proxy", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateProxyEnabled = (id: number, enabled: boolean) =>
  api<ProxyEntry>(`/api/admin/proxy/${id}`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });

export const deleteProxy = (id: number) =>
  api<{ deleted: boolean }>(`/api/admin/proxy/${id}`, { method: "DELETE" });

// --- GHG6 P0: indicators, parser, ping, alerts ---

export interface ProxyEditPatch {
  server?: string;
  port?: number;
  type?: ProxyType;
  secret?: string;
  clear_secret?: boolean;
  enabled?: boolean;
}

export const patchProxy = (id: number, patch: ProxyEditPatch) =>
  api<ProxyEntry>(`/api/admin/proxy/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export interface ProxySelftest {
  ok: boolean;
  mode_used: string;
  proxy_id: number | null;
  latency_ms: number | null;
  error: string | null;
  bot_active: boolean;
}

export interface ProxyPing {
  proxy_id: number;
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
}

export interface ProxyStatus {
  bot_active: boolean;
  mode: ProxyMode;
  pool_size: number;
  alive_count: number;
  last_selftest: ProxySelftest | null;
  last_error: {
    at: string;
    message: string;
    mode_used: string;
    proxy_id: number | null;
  } | null;
}

export const proxySelftest = () =>
  api<ProxySelftest>("/api/admin/proxy/selftest", { method: "POST" });

export const proxyPing = (id: number) =>
  api<ProxyPing>(`/api/admin/proxy/${id}/ping`, { method: "POST" });

export const proxyPingAll = () =>
  api<ProxyPing[]>("/api/admin/proxy/ping-all", { method: "POST" });

export const proxyDeleteDead = () =>
  api<{ deleted: number }>("/api/admin/proxy/delete-dead", { method: "POST" });

export interface ProxyDraft {
  server: string;
  port: number;
  secret: string | null;
  type: ProxyType;
}

export const proxyParse = (text: string) =>
  api<{ parsed: ProxyDraft[] }>("/api/admin/proxy/parse", {
    method: "POST",
    body: JSON.stringify({ text }),
  });

export const proxyStatus = () =>
  api<ProxyStatus>("/api/admin/proxy/status");

export const proxyClearLastError = () =>
  api<{ cleared: boolean }>("/api/admin/proxy/status/last-error", {
    method: "DELETE",
  });

export interface ProxyAlerts {
  enabled: boolean;
  last_alert_at: string | null;
}

export const proxyAlertsGet = () =>
  api<ProxyAlerts>("/api/admin/proxy/alerts");

export const proxyAlertsSet = (enabled: boolean) =>
  api<ProxyAlerts>("/api/admin/proxy/alerts", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });


// GHG6 CL0: master-toggle нового таймлайн-вида календаря.
// GET читает любой залогиненный — это нужно CalendarView, чтобы выбрать legacy/new ветку.
// PUT — только админ.
export interface CalendarTimelineFlag {
  enabled: boolean;
}

export const fetchCalendarTimelineFlag = () =>
  api<CalendarTimelineFlag>("/api/admin/calendar/timeline");

export const setCalendarTimelineFlag = (enabled: boolean) =>
  api<CalendarTimelineFlag>("/api/admin/calendar/timeline", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
