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
  reason_text: string | null; // GHG8 T1.2
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
  // GHG6 M: backend стал возвращать также "date" и "unknown" для системных,
  // плюс "reminder" для DB-напоминаний.
  kind: "cron" | "interval" | "date" | "reminder" | "unknown";
  label: string;
  next_run_at: string | null;
  detail: string | null;
  // GHG6 M: тот же что kind, но не «соврёт» если бэкенд не отдаёт (default).
  trigger_kind?: "cron" | "interval" | "date" | "reminder" | "unknown";
  // GHG6 M: системные job'ы (proxy_health) приходят с editable=false —
  // фронт скрывает у них кнопки «Изменить» / «Отменить».
  editable?: boolean;
}

export const fetchScheduledJobs = () =>
  api<ScheduledJob[]>("/api/admin/jobs");

// GHG6 N1: история опросов и игр.
export interface PollHistoryVote {
  user_id: number;
  display_name: string | null;
  voted_at: string;
}

export interface PollHistoryOption {
  id: number;
  label: string | null;
  starts_at: string | null;
  ends_at: string | null;
  votes: PollHistoryVote[];
}

export interface PollHistoryRow {
  poll_id: number;
  kind: string | null;
  question: string;
  created_by: number;
  created_at: string;
  closes_at: string | null;
  closed: boolean;
  tg_message_id: number | null;
  game_nomination_id: number | null;
  options: PollHistoryOption[];
}

export const fetchPollsHistory = (limit = 30) =>
  api<PollHistoryRow[]>(`/api/admin/polls/history?limit=${limit}`);

export const fetchGamesHistory = (limit = 30) =>
  api<PollHistoryRow[]>(`/api/admin/games/history?limit=${limit}`);

// GHG6 N2: master-toggle и история 5★ feedback-опросов по встречам.
export interface MeetingFeedbackSettings {
  enabled: boolean;
  notify_absence: boolean;
  absence_weight_delta: number;
}

export const fetchMeetingFeedbackSettings = () =>
  api<MeetingFeedbackSettings>("/api/admin/meeting-feedback");

export const updateMeetingFeedbackSettings = (body: MeetingFeedbackSettings) =>
  api<MeetingFeedbackSettings>("/api/admin/meeting-feedback", {
    method: "PUT",
    body: JSON.stringify(body),
  });

export interface MeetingFeedbackRow {
  meeting_id: number;
  meeting_title: string;
  meeting_starts_at: string;
  user_id: number;
  display_name: string | null;
  rating: number | null;
  was_absent: boolean;
  reason_text: string | null;
  created_at: string;
}

export const fetchMeetingFeedbackHistory = (limit = 50) =>
  api<MeetingFeedbackRow[]>(`/api/admin/meeting-feedback/history?limit=${limit}`);

// GHG6 M3: cancel = пропустить ближайший запуск (для recurring) / удалить (one-shot).
export const cancelScheduledJob = (jobId: string) =>
  api<void>(`/api/admin/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });

// GHG6 M2: подвинуть next_run_time job'а на указанный момент (UTC ISO).
export const rescheduleScheduledJob = (jobId: string, runAtIso: string) =>
  api<ScheduledJob>(`/api/admin/jobs/${encodeURIComponent(jobId)}/reschedule`, {
    method: "POST",
    body: JSON.stringify({ run_at: runAtIso }),
  });

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

// --- T3.4: advice («магический шар») ---

export interface AdviceConfig {
  enabled: boolean;
  phrases: string[];
}

export const fetchAdvice = () => api<AdviceConfig>("/api/admin/advice");

export const updateAdvicePhrases = (phrases: string[]) =>
  api<AdviceConfig>("/api/admin/advice/phrases", {
    method: "PUT",
    body: JSON.stringify({ phrases }),
  });

export const updateAdviceEnabled = (enabled: boolean) =>
  api<AdviceConfig>("/api/admin/advice/enabled", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });

// --- T3.1: снапшот/экспорт базы причин-реакций ---

export interface PhraseSnapshot {
  format: string;
  version: number;
  pools: Record<string, string[]>;
  use_counts: Record<string, Record<string, number>>;
  personas: Array<{
    telegram_id: number;
    display_name: string;
    persona_text: string;
  }>;
}

export interface SnapshotImportSummary {
  mode: "replace" | "merge";
  pools: Record<string, { count: number }>;
  personas: { restored?: number; skipped?: number };
}

export const fetchPhrasesSnapshot = () =>
  api<PhraseSnapshot>("/api/admin/phrases/snapshot");

export const importPhrasesSnapshot = (
  snapshot: unknown,
  mode: "replace" | "merge",
) =>
  api<SnapshotImportSummary>("/api/admin/phrases/snapshot/import", {
    method: "POST",
    body: JSON.stringify({ snapshot, mode }),
  });

// --- T3.3: алёрты «лох/чухан не запостился» ---

export interface PostingLoserAlert {
  outbox_id: number;
  rolled_at: string | null;
  loser_name: string | null;
  reason_text: string | null;
  attempts: number;
  last_error: string | null;
}

export interface PostingChukhanAlert {
  week_start: string;
  user_name: string | null;
  created_at: string | null;
}

export interface PostingAlerts {
  total: number;
  loser: PostingLoserAlert[];
  chukhan: PostingChukhanAlert | null;
}

export const fetchPostingAlerts = () =>
  api<PostingAlerts>("/api/admin/posting-alerts");

export const retryChukhanPosting = () =>
  api<{ delivered: boolean }>("/api/admin/posting-alerts/chukhan-retry", {
    method: "POST",
  });

// --- GHG6 AD6: Chukhan reasons CRUD (отдельные шаблоны фраз чухана) ---

export const fetchChukhanReasons = () =>
  api<LoserReasons>("/api/admin/chukhan-reasons");

export const updateChukhanReasons = (reasons: string[]) =>
  api<LoserReasons>("/api/admin/chukhan-reasons", {
    method: "PUT",
    body: JSON.stringify({ reasons }),
  });

// --- GHG8 Q5: диагностика + сброс причин чухана к дефолтам ---

export interface ChukhanReasonsRaw {
  key: string;
  key_present: boolean;
  raw_value: string | null;
  raw_len: number;
  parse_ok: boolean;
  parsed_count: number;
  using_default: boolean;
  default_count: number;
}

export const fetchChukhanReasonsRaw = () =>
  api<ChukhanReasonsRaw>("/api/admin/chukhan-reasons/raw");

export const resetChukhanReasons = () =>
  api<LoserReasons>("/api/admin/chukhan-reasons/reset", { method: "POST" });

// --- GHG6 E5: use-counts фраз (вес = 1/(1+use_count)) ---

export interface ReasonUseCountsOut {
  counts: Record<string, number>;
}
export interface ReasonUseCountsCleared {
  cleared: number;
}

export const fetchLoserReasonUseCounts = () =>
  api<ReasonUseCountsOut>("/api/admin/loser-reasons/use-counts");

export const clearLoserReasonUseCounts = () =>
  api<ReasonUseCountsCleared>("/api/admin/loser-reasons/use-counts", {
    method: "DELETE",
  });

export const fetchChukhanReasonUseCounts = () =>
  api<ReasonUseCountsOut>("/api/admin/chukhan-reasons/use-counts");

export const clearChukhanReasonUseCounts = () =>
  api<ReasonUseCountsCleared>("/api/admin/chukhan-reasons/use-counts", {
    method: "DELETE",
  });

// Точечная правка счётчика одной фразы (count=0 — сброс). Возвращает
// свежий словарь {фраза: count} по всему пулу.
export const setLoserReasonUseCount = (phrase: string, count: number) =>
  api<ReasonUseCountsOut>("/api/admin/loser-reasons/use-counts", {
    method: "PUT",
    body: JSON.stringify({ phrase, count }),
  });

export const setChukhanReasonUseCount = (phrase: string, count: number) =>
  api<ReasonUseCountsOut>("/api/admin/chukhan-reasons/use-counts", {
    method: "PUT",
    body: JSON.stringify({ phrase, count }),
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
  // GHG8 P3: режим иммунитета именинника к лоху/чухану. Опционален —
  // старые серверы поля не отдают, фронт подставляет "announce".
  immunity_mode?: "announce" | "silent";
}

export interface ScheduledChukhanIO {
  weekday: number; // 0=Mon
  window_start: string;
  window_end: string;
}

// GHG8 P7: «мёртвый чат» — пост при долгой тишине (пороги 24ч…год).
// Опционален: старые серверы блок не отдают.
export interface ScheduledDeadChatIO {
  enabled: boolean;
}

export interface ScheduledSettingsIO {
  reminders: ScheduledRemindersIO;
  loser: ScheduledLoserIO;
  phrases: ScheduledPhrasesIO;
  avatars: ScheduledAvatarsIO;
  birthdays: ScheduledBirthdaysIO;
  chukhan: ScheduledChukhanIO;
  dead_chat?: ScheduledDeadChatIO;
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

// GHG6 L: режим сбора фраз. 'words' — отдельные слова, 'phrases' — целые фразы
// из истории, 'mix' (default) — оба пула вместе. Серверный default — 'mix'
// для обратной совместимости со старыми клиентами.
export type RandomPhrasesMode = "words" | "phrases" | "mix";

// GHG8 P6.3: версия генератора — legacy (нарезка сообщений v1) | personas
// (типажи v2). Расписание/шансы общие, переключается только composer.
export type PhraseGeneratorVersion = "legacy" | "personas";

export interface RPGenerator {
  count_min: number;
  count_max: number;
  lookback_days: number;
  collective_chance: number;
  user_chance: number;
  mode: RandomPhrasesMode;
  // P13: карантин свежести — сообщения младше N часов почти не цитируются
  // (вес 0..1 вместо 1.0). Убирает «передразнивание» последних сообщений.
  recency_quarantine_hours: number;
  recency_quarantine_weight: number;
  // GHG8 P6.3: старые серверы не возвращают поле → undefined → 'legacy'.
  generator_version?: PhraseGeneratorVersion;
}

export const fetchRPGenerator = () =>
  api<RPGenerator>("/api/admin/random-phrases/generator");

export const updateRPGenerator = (body: RPGenerator) =>
  api<RPGenerator>("/api/admin/random-phrases/generator", {
    method: "PUT",
    body: JSON.stringify(body),
  });

// --- GHG8 P6.1: персоналии участников (генератор v2) ---
// Тексты живут только в Neon (открытый git); сидинг — руками через админку
// (P6.1.b). Пустой текст в updatePersona = удаление персоналии.

export interface PersonaRow {
  user_id: number;
  display_name: string;
  persona_text: string | null;
  templates_count: number;
  broken_templates_count: number;
}

export const fetchPersonas = () => api<PersonaRow[]>("/api/admin/personas");

export const updatePersona = (userId: number, personaText: string) =>
  api<PersonaRow>(`/api/admin/personas/${userId}`, {
    method: "PUT",
    body: JSON.stringify({ persona_text: personaText }),
  });

export const previewPersona = (userId: number, personaText: string) =>
  api<{ phrase: string | null }>(`/api/admin/personas/${userId}/preview`, {
    method: "POST",
    body: JSON.stringify({ persona_text: personaText }),
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

// GHG6 E1.2: POST /admin/proxy теперь возвращает {proxy, created, ping_result}.
// ping_result=null означает «не пинговали» (например, проксь создан как enabled=false).
// При type=mtproto ping_result.error = "ping_not_supported_for_type:mtproto" — UI должен
// показывать это отдельно от «мёртв».
export interface ProxyAddResult {
  proxy: ProxyEntry;
  created: boolean;
  ping_result: ProxyPing | null;
}

export const createProxy = (body: {
  server: string;
  port: number;
  type: ProxyType;
  secret?: string | null;
  enabled?: boolean;
}) =>
  api<ProxyAddResult>("/api/admin/proxy", {
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

// GHG6 E1.1: ring-buffer ошибок добавления прокси.
export interface ProxyAddErrorItem {
  at: string;
  reason: string;  // proxy_pool_full | db_error | validation_error
  detail: string;
  draft: Record<string, unknown>;
}

export const proxyGetAddErrors = () =>
  api<{ errors: ProxyAddErrorItem[] }>("/api/admin/proxy/add-errors");

export const proxyClearAddErrors = () =>
  api<{ cleared: boolean }>("/api/admin/proxy/add-errors", { method: "DELETE" });

// GHG6 E1.4: bootstrap-fetch публичного списка прокси.
export interface ProxyBootstrapResult {
  source_url: string;
  fetched: number;
  pinged_alive: number;
  added: number;
  skipped_duplicate: number;
  skipped_dead: number;
  skipped_pool_full: number;
  errors: string[];
}

export const proxyBootstrapFetch = (urlOverride?: string) =>
  api<ProxyBootstrapResult>("/api/admin/proxy/bootstrap-fetch", {
    method: "POST",
    body: JSON.stringify(urlOverride ? { url_override: urlOverride } : {}),
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

// --- GHG6 E11: bot pause + zaebal settings ---

export interface BotPauseState {
  active: boolean;
  id: number | null;
  started_at: string | null;
  ends_at: string | null;
  reason: string | null;
}

export interface ZaebalSettings {
  threshold: number;
  duration_days: number;
  poll_hours: number;
  vote_duration_days: number;
  auto_enabled: boolean;
  auto_max_per_month: number;
}

export const fetchBotPauseCurrent = () =>
  api<BotPauseState>("/api/admin/bot-pause/current");

export const startBotPause = (durationDays: number | null) =>
  api<BotPauseState>("/api/admin/bot-pause/start", {
    method: "POST",
    body: JSON.stringify({ duration_days: durationDays }),
  });

export const stopBotPause = () =>
  api<BotPauseState>("/api/admin/bot-pause/stop", { method: "POST" });

export const fetchZaebalSettings = () =>
  api<ZaebalSettings>("/api/admin/zaebal-settings");

export const updateZaebalSettings = (s: ZaebalSettings) =>
  api<ZaebalSettings>("/api/admin/zaebal-settings", {
    method: "PUT",
    body: JSON.stringify(s),
  });

// --- GHG6 E9: реакции бота на @-mention и reply ---

export interface BotReactionsSettings {
  mention_enabled: boolean;
  reply_all_enabled: boolean;
  reply_except_phrases_enabled: boolean;
}

export const fetchBotReactions = () =>
  api<BotReactionsSettings>("/api/admin/bot-reactions");

export const updateBotReactions = (s: BotReactionsSettings) =>
  api<BotReactionsSettings>("/api/admin/bot-reactions", {
    method: "PUT",
    body: JSON.stringify(s),
  });

// --- GHG7 P5: реакции бота на медиа (мемы/подборки) ---
// Пулы фраз/эмодзи — JSON-списки в admin_config (бэк: services/media_reactions.py).
// Поведение — один честный ролл на мем. chance_pct = вероятность среагировать
// вообще; wait_window_min = грейс-окно для режима wait_then_chance.

export type MediaMode = "always" | "chance" | "wait_then_chance" | "never";
export type MediaSingleResponseMode = "emoji" | "phrase" | "both" | "random_one";

export interface MediaReactionsSettings {
  enabled: boolean;
  single_enabled: boolean;
  collection_enabled: boolean;
  mode: MediaMode;
  chance_pct: number;
  wait_window_min: number;
  single_response_mode: MediaSingleResponseMode;
}

export interface MediaPhrases {
  phrases: string[];
}

export interface MediaForceResult {
  ok: boolean;
  message_id: number;
}

export const fetchMediaSettings = () =>
  api<MediaReactionsSettings>("/api/admin/media-reactions/settings");

export const updateMediaSettings = (s: MediaReactionsSettings) =>
  api<MediaReactionsSettings>("/api/admin/media-reactions/settings", {
    method: "PUT",
    body: JSON.stringify(s),
  });

export const fetchMediaSinglePhrases = () =>
  api<MediaPhrases>("/api/admin/media-reactions/single-phrases");
export const updateMediaSinglePhrases = (phrases: string[]) =>
  api<MediaPhrases>("/api/admin/media-reactions/single-phrases", {
    method: "PUT",
    body: JSON.stringify({ phrases }),
  });

export const fetchMediaCollectionPhrases = () =>
  api<MediaPhrases>("/api/admin/media-reactions/collection-phrases");
export const updateMediaCollectionPhrases = (phrases: string[]) =>
  api<MediaPhrases>("/api/admin/media-reactions/collection-phrases", {
    method: "PUT",
    body: JSON.stringify({ phrases }),
  });

// rejected — эмодзи вне поддерживаемого TG набора реакций, отброшенные при
// сохранении (п.15). Экран показывает их админу, а не глотает молча.
export interface MediaEmojiWhitelist {
  phrases: string[];
  rejected: string[];
}
export const fetchMediaEmojiWhitelist = () =>
  api<MediaPhrases>("/api/admin/media-reactions/emoji-whitelist");
export const updateMediaEmojiWhitelist = (phrases: string[]) =>
  api<MediaEmojiWhitelist>("/api/admin/media-reactions/emoji-whitelist", {
    method: "PUT",
    body: JSON.stringify({ phrases }),
  });

// kind: "single" | "collection" — принудительная реакция на последнее медиа.
export const forceMediaReaction = (kind: "single" | "collection") =>
  api<MediaForceResult>(`/api/admin/media-reactions/force/${kind}`, {
    method: "POST",
  });

// --- GHG6 E10: avatars — разовый sync + одноразовое расписание ---

export interface AvatarsSyncNowResult {
  synced: number;
}
export interface AvatarsScheduleOnce {
  scheduled: boolean;
  run_at: string | null;
}

export const avatarsSyncNow = () =>
  api<AvatarsSyncNowResult>("/api/admin/avatars/sync-now", { method: "POST" });

export const avatarsScheduleOnceGet = () =>
  api<AvatarsScheduleOnce>("/api/admin/avatars/schedule-once");

export const avatarsScheduleOncePost = (runAtIso: string) =>
  api<AvatarsScheduleOnce>("/api/admin/avatars/schedule-once", {
    method: "POST",
    body: JSON.stringify({ run_at: runAtIso }),
  });

export const avatarsScheduleOnceDelete = () =>
  api<AvatarsScheduleOnce>("/api/admin/avatars/schedule-once", {
    method: "DELETE",
  });

// GHG8 (18.06 #2): ручная подстановка аватарки на участника.
export interface AvatarRow {
  user_id: number;
  display_name: string;
  display_url: string | null;
  has_tg_photo: boolean;
  manual_url: string | null;
  synced_at: string | null;
}

export const avatarsList = () =>
  api<AvatarRow[]>("/api/admin/avatars/list");

export const avatarsSetManual = (userId: number, manualUrl: string | null) =>
  api<AvatarRow>(`/api/admin/avatars/${userId}/manual`, {
    method: "PUT",
    body: JSON.stringify({ manual_url: manualUrl }),
  });

// --- GHG6 E6: номинированные игры + голосование ---

export interface GameNomination {
  id: number;
  name: string;
  added_by_tg_id: number;
  added_at: string;
}

export interface GameNominationsList {
  items: GameNomination[];
  max_active: number;
}

export interface GamesPollCreateResult {
  poll_id: number;
  tg_message_id: number | null;
  options_count: number;
  closes_at: string | null;
  follow_up_when: boolean;
}

export const fetchGameNominations = () =>
  api<GameNominationsList>("/api/admin/games");

export const addGameNomination = (name: string) =>
  api<GameNomination>("/api/admin/games", {
    method: "POST",
    body: JSON.stringify({ name }),
  });

export const removeGameNomination = (id: number) =>
  api<void>(`/api/admin/games/${id}`, { method: "DELETE" });

export const createGamesPoll = (input: {
  timeout_hours: number;
  nomination_ids?: number[];
  follow_up_when: boolean;
  /** GHG6 G2: закрепить опрос. null → дефолт из admin_config. */
  pin?: boolean | null;
}) =>
  api<GamesPollCreateResult>("/api/admin/games/poll-create", {
    method: "POST",
    body: JSON.stringify(input),
  });

// --- G2.10 + G3.6: единый блок дефолтов опросов в чате ---

export interface PollsDefaults {
  /** G2: при создании опроса с pin=null — берётся это значение. */
  pin_default: boolean;
  /** G3: авто-закрытие опроса при достижении кворума уникальных голосов. */
  quorum_auto_close: boolean;
  /** G3: сколько уникальных голосов = «все живые». Default 5. */
  live_participants_count: number;
  /** G3: пинить ли announce-сообщение с результатами. */
  pin_result: boolean;
}

export const fetchPollsDefaults = () =>
  api<PollsDefaults>("/api/admin/polls/defaults");

export const updatePollsDefaults = (body: PollsDefaults) =>
  api<PollsDefaults>("/api/admin/polls/defaults", {
    method: "PUT",
    body: JSON.stringify(body),
  });

// --- GHG8 P14: рестарт HF Space (кнопка + расписание) ---

export interface SpaceRestartSchedule {
  mode: "off" | "once" | "interval";
  /** ISO-datetime для mode=once. */
  at: string | null;
  /** Часы для mode=interval (1..720). */
  every_hours: number | null;
}

export interface SpaceRestartStatus {
  /** env HF_TOKEN задан на Space — рестарт вообще возможен. */
  available: boolean;
  schedule: SpaceRestartSchedule;
  last_restart_at: string | null;
  next_restart_at: string | null;
}

export const fetchSpaceRestartSettings = () =>
  api<SpaceRestartStatus>("/api/admin/space/restart-settings");

export const updateSpaceRestartSettings = (s: SpaceRestartSchedule) =>
  api<SpaceRestartStatus>("/api/admin/space/restart-settings", {
    method: "PUT",
    body: JSON.stringify(s),
  });

export const restartSpaceNow = () =>
  api<{ status: string }>("/api/admin/space/restart", { method: "POST" });
