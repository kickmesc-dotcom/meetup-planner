import { api } from "./client";
import { getInitData } from "@/tg/webapp";

// Э21: загрузка голосового и прослушивание — не через `api()`: там всегда
// ставится JSON-заголовок, а для `FormData` браузер сам выставляет boundary.
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

/**
 * GHG10 Э5: поверхности игровой системы (ранги, опыт, ачивки).
 *
 * Сервер отдаёт уже готовый к отрисовке payload — фронт не пересчитывает
 * уровни/пороги (все числа живут в `backend/app/services/game/config.py`).
 */

export interface GameRank {
  level: number;
  name: string;
  /** Цвет плашки ранга; контраст текста считает фронт (RankPlaque). */
  hex: string;
  bold: boolean;
}

export interface GameFeature {
  code: string;
  title: string;
  /** Человеческое «куда зайти, что нажать, что будет» (Э19). */
  description?: string;
  /** GHG11(4): вкладка мини-аппа, куда ведёт кнопка «Открыть» в анонсе. */
  tab?: string;
  /** GHG11(4): id DOM-элемента для доскролла на этой вкладке. */
  anchor?: string;
  /** GHG11(4): подраздел админки, который открыть сразу ("loser"/"chukhan"). */
  admin_section?: string;
}

/**
 * GHG11(4): миниатюра участника под блоком задания/подборки/раунда.
 * Общая форма для голосовых сдач, владельцев треков и угадавших в муз-гейме.
 */
export interface FeedParticipant {
  user_id?: number;
  user_name: string | null;
  avatar_url?: string | null;
  xp?: number;
  likes?: number;
  role?: string;
}

export interface GameLevelUp {
  from_level: number;
  from_rank: string;
  to_level: number;
  to_rank: string;
  unlocked: GameFeature[];
}

export interface GameDailyEvent {
  event: string;
  title: string;
  points: number;
  count: number;
}

export interface GameAchievement {
  code: string;
  title: string;
  description: string;
  icon: string;
  points: number;
  kind: "counter" | "threshold" | "instant" | string;
  collected: boolean;
  unlocked_at: string | null;
  progress: number | null;
  threshold: number | null;
  tiers: number[];
  /** Взятые юбилейные тиры (×10/×20/…). База «разовая» и тиры — разные ачивки. */
  collected_tiers: number[];
}

export interface GameXpRule {
  code: string;
  title: string;
  points: number;
  limit: string | null;
}

export interface GameProfile {
  enabled: boolean;
  xp: number;
  level: number;
  max_level: number;
  rank: GameRank | null;
  rank_name: string;
  supreme: boolean;
  /** Э18: собраны 100% ачивок — особый титул «Идеальный червь». */
  completionist: boolean;
  custom_rank_title: string | null;
  custom_name: string | null;
  avatar_manual_url: string | null;
  xp_into_level: number;
  xp_to_next: number | null;
  at_max: boolean;
  prestige: number;
  unlocked: GameFeature[];
  level_up: GameLevelUp | null;
  today: GameDailyEvent[];
  today_total: number;
  achievements: GameAchievement[];
  xp_rules: GameXpRule[];
}

export interface AchievementStat {
  code: string;
  title: string;
  icon: string;
  holders: number;
  total: number;
  percent: number;
}

export interface RankRow {
  user_id: number;
  xp: number;
  level: number;
  rank_name: string;
  hex: string;
  bold: boolean;
  supreme: boolean;
}

export interface GameCustomizePatch {
  custom_name?: string | null;
  custom_rank_title?: string | null;
  avatar_manual_url?: string | null;
}

export const fetchMyGame = () => api<GameProfile>("/api/me/game");

/** Э8: своё имя / название ранга / аватарка — каждое по своему рангу. */
export const updateGameProfile = (patch: GameCustomizePatch) =>
  api<GameProfile>("/api/me/game/profile", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const ackLevelUp = () =>
  api<void>("/api/me/game/level-up/ack", { method: "POST" });

export const fetchAchievementStats = () =>
  api<AchievementStat[]>("/api/game/achievements");

export const fetchRanksChart = () => api<RankRow[]>("/api/game/ranks");

/** Э19: собранная ачивка в чужом профиле (без прогресса/тиров). */
export interface GuestAchievement {
  code: string;
  title: string;
  icon: string;
  /** GHG11(3): когда и за что — раскрывается по тапу. */
  description?: string | null;
  points?: number;
  unlocked_at?: string | null;
}

/** GHG11(3): событие звания в истории участника. */
export interface GuestTitleEvent {
  at: string;
  reason: string | null;
}

/** Э19: чужой игровой профиль «глазами гостя» — факты без настроек. */
export interface GuestProfile {
  enabled: boolean;
  telegram_id: number;
  user_id: number;
  name: string;
  avatar_url: string | null;
  level: number;
  rank: GameRank | null;
  rank_name: string;
  xp: number;
  /** GHG11(7): сколько до следующего уровня (как в своём профиле). */
  max_level: number;
  xp_into_level: number;
  xp_to_next: number | null;
  at_max: boolean;
  prestige: number;
  supreme: boolean;
  completionist: boolean;
  loser_count: number;
  chukhan_count: number;
  rank_position: number | null;
  ranks_total: number;
  achievements_collected: number;
  achievements_total: number;
  /** GHG11(3): процент открытых ачивок (для сравнения со своими). */
  achievements_percent: number;
  /** GHG11(3): история званий — когда и за что был лохом/чуханом. */
  loser_history: GuestTitleEvent[];
  chukhan_history: GuestTitleEvent[];
  /** GHG11(3): суммарно сколько участник продержал червя (дней). */
  worm_total_days: number;
  achievements: GuestAchievement[];
  /** GHG11: сегодняшние «носимые» звания с причинами (плашка над головой). */
  today: GuestTodayTitle | null;
}

/** GHG11: звания «сегодня» — лох дня / чухан недели / червь-пидор. */
export interface GuestTodayTitle {
  loser: boolean;
  loser_reason: string | null;
  chukhan: boolean;
  chukhan_reason: string | null;
  worm: boolean;
}

/** Э19: профиль участника по внутреннему id (клик по аватарке на календаре). */
export const fetchGuestProfile = (userId: number) =>
  api<GuestProfile>(`/api/game/players/${userId}`);

/**
 * Э22: подробности записи ленты для раскрытия карточки.
 *
 * Состав зависит от `kind`: у ачивки — «за что дана», у голосового — условие и
 * окно, у подборки — треки с лайками. Поля необязательные: тип читается мягко.
 */
export interface FeedDetail {
  code?: string;
  description?: string;
  points?: number;
  title?: string;
  /** GHG11(8): id голосового задания — по нему карточка находит своё задание. */
  task_id?: number;
  /**
   * GHG11(8): интерфейс участия в задании-призыве прямо в ленте.
   *
   * Приходит у анонса открытого события: `options` — кнопки-варианты,
   * `needs_text` — поле ввода. Ответ уходит тем же путём, что и сообщение в
   * чате, поэтому «первый подходящий забирает XP» сохраняется.
   */
  activity?: {
    id: number;
    code: string;
    options: ActivityOption[];
    needs_text: boolean;
    expires_at: string | null;
    answered_by_me: boolean;
  };
  condition?: string;
  opened_at?: string | null;
  closed_at?: string | null;
  expires_at?: string | null;
  reward?: number;
  closed?: boolean;
  track_count?: number;
  selection_id?: number;
  week_start?: string | null;
  reason?: string | null;
  submissions?: {
    id: number;
    user_id: number;
    user_name: string | null;
    duration: number | null;
    likes?: number;
    liked?: boolean;
    /** GHG11(4): сколько XP получил участник за этот вариант. */
    xp?: number;
    /** GHG11(4): аватарка для миниатюры участника под заданием. */
    avatar_url?: string | null;
  }[];
  /** GHG11(4): компактные участники для музыки и муз-гейма. */
  participants?: FeedParticipant[];
  /** GHG11(4): лайки загаданного трека в муз-гейме. */
  track_likes?: number;
  tracks?: {
    id: number;
    kind: string;
    title: string | null;
    performer: string | null;
    url: string | null;
    likes: number;
    liked: boolean;
    /** GHG11(4): владелец трека — для миниатюр участников подборки. */
    user_id?: number;
    user_name?: string | null;
    avatar_url?: string | null;
  }[];
}

/** Э20: одна запись ленты активности (ачивка/лох/чухан/событие). */
export interface FeedItem {
  id: string;
  source: string;
  kind: string;
  icon: string;
  title: string;
  text: string;
  at: string;
  user_id: number | null;
  user_name: string | null;
  user_telegram_id: number | null;
  avatar_url: string | null;
  /** GHG11: эмодзи-плашки званий над головой (сегодня лох/чухан/червь). */
  badges?: string[];
  /** Э22: подробности раскрывающейся карточки (см. `FeedDetail`). */
  detail?: FeedDetail | null;
}

export interface GameFeed {
  enabled: boolean;
  items: FeedItem[];
  next_offset: number | null;
  /** Э21: доступные типы записей — для чипов-фильтров. */
  kinds: string[];
  /** GHG11(4): "compact" (новый вид) или "classic" (старый). */
  feed_view?: string;
}

/**
 * Э20/Э21: лента активности для вкладки «Лента» мини-аппа.
 * `scope="mine"` — только записи текущего игрока;
 * `kinds` — фильтр по типам через запятую (пусто/undefined = все).
 */
export const fetchFeed = (opts?: {
  scope?: "all" | "mine";
  limit?: number;
  offset?: number;
  kinds?: string;
}) => {
  const params = new URLSearchParams();
  params.set("scope", opts?.scope ?? "all");
  params.set("limit", String(opts?.limit ?? 30));
  params.set("offset", String(opts?.offset ?? 0));
  if (opts?.kinds) params.set("kinds", opts.kinds);
  return api<GameFeed>(`/api/game/feed?${params.toString()}`);
};

/** Э21: подписи и иконки типов записей — те же, что отдаёт бэкенд (`feed.py`). */
export const FEED_KIND_LABELS: Record<string, { icon: string; title: string }> = {
  achievement: { icon: "🏆", title: "Ачивки" },
  loser: { icon: "👑", title: "Лохи" },
  chukhan: { icon: "🧹", title: "Чуханы" },
  voice: { icon: "🎙", title: "Голосовые" },
  music: { icon: "🎧", title: "Музыка" },
  music_game: { icon: "🎵", title: "Музык-игры" },
  event: { icon: "⚡️", title: "События" },
  holiday: { icon: "🎊", title: "Праздники" },
  contraband: { icon: "💰", title: "Контрабанда" },
  memorial: { icon: "🕯", title: "Поминовения" },
  // GHG11: активность механик без своей таблицы (совет, червь, реакции,
  // номинации). Метка должна совпадать с `feed.FEED_TITLES[FEED_FEATURE]`.
  feature: { icon: "✨", title: "Активность" },
};

/** GHG11: вид записи ленты «feature» — активность механик. */
export const FEED_FEATURE_KIND = "feature";

/**
 * Э21: активности в мини-аппе, когда бот молчит в чате.
 *
 * Вопросы (случайные события) можно закрыть кнопкой/текстом прямо в ленте, а
 * голосовое задание — сдать, убрать и прослушать, не покидая приложение.
 */
export interface ActivityOption {
  label: string;
  xp: number;
}

export interface GameActivity {
  id: number;
  code: string;
  text: string;
  options: ActivityOption[];
  needs_text: boolean;
  expires_at: string | null;
  answered_by_me: boolean;
}

export interface ActivitiesOut {
  enabled: boolean;
  items: GameActivity[];
}

export const fetchActivities = () =>
  api<ActivitiesOut>("/api/game/activities");

export interface ActivityAnswerResult {
  ok: boolean;
  status: string;
  xp: number;
}

/** Ответ на вопрос: либо подпись варианта, либо свободный текст. */
export const answerActivity = (id: number, text: string) =>
  api<ActivityAnswerResult>(`/api/game/activities/${id}/answer`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });

export interface VoiceSubmission {
  id: number;
  user_id: number;
  user_name: string | null;
  duration: number | null;
  submitted_at: string | null;
  is_mine: boolean;
  /** GHG11: лайки варианта. */
  likes: number;
  liked: boolean;
}

/** GHG11: поставить/снять лайк варианту голосового (toggle). */
export const likeVoiceSubmission = (id: number) =>
  api<{ ok: boolean; liked: boolean; likes: number }>(
    `/api/game/voice/submissions/${id}/like`,
    { method: "POST" },
  );

/** GHG11: модерация ленты — админ удаляет для всех, участник скрывает у себя. */
export const deleteFeedItem = (itemId: string) =>
  api<{ ok: boolean; hard?: boolean }>("/api/game/feed/delete", {
    method: "POST",
    body: JSON.stringify({ item_id: itemId }),
  });
export const restoreFeedItem = (itemId: string) =>
  api<{ ok: boolean }>("/api/game/feed/restore", {
    method: "POST",
    body: JSON.stringify({ item_id: itemId }),
  });
export const hideFeedItem = (itemId: string) =>
  api<{ ok: boolean }>("/api/game/feed/hide", {
    method: "POST",
    body: JSON.stringify({ item_id: itemId }),
  });
export const unhideFeedItem = (itemId: string) =>
  api<{ ok: boolean }>("/api/game/feed/unhide", {
    method: "POST",
    body: JSON.stringify({ item_id: itemId }),
  });

/** GHG11: магический шар прямо из ленты. */
export interface AdviceResult {
  ok: boolean;
  status: string;
  text: string;
  /** GHG11(3): фирменный ответ «иди на хуй» (10% шанс). */
  cursed?: boolean;
  question?: string | null;
  target?: "feed" | "header";
}

/**
 * GHG11(3): закрутить магический шар.
 * `target="feed"` (по умолчанию) — результат уходит в ленту от лица игрока;
 * `target="header"` — вернуть текст, показать в шапке.
 */
export const askAdvice = (question?: string, target: "feed" | "header" = "feed") =>
  api<AdviceResult>("/api/game/advice", {
    method: "POST",
    body: JSON.stringify({ question: question?.trim() || null, target }),
  });

/** GHG11(3): админский ручной «прогон фразы» — фраза уходит в ленту. */
export interface PhraseRunResult {
  ok: boolean;
  status: string;
  text: string;
}
export const runPhrase = () =>
  api<PhraseRunResult>("/api/game/phrases", { method: "POST" });

/** GHG11: номинации игр и голосование «во что сыграем» в аппе. */
export interface NominationItem {
  id: number;
  name: string;
  votes: number;
  voted: boolean;
}
export interface Nominations {
  enabled: boolean;
  can_add: boolean;
  max_active: number;
  my_vote_id: number | null;
  items: NominationItem[];
}
export const fetchNominations = () => api<Nominations>("/api/game/nominations");
export const addNomination = (name: string) =>
  api<Nominations>("/api/game/nominations", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
export const voteNomination = (id: number) =>
  api<{ ok: boolean; voted: boolean; votes: number }>(
    `/api/game/nominations/${id}/vote`,
    { method: "POST" },
  );

/** GHG11: червь-господин — состояние и передача из аппа. */
export interface WormState {
  enabled: boolean;
  is_owner: boolean;
  owner_user_id: number | null;
  owner_name: string | null;
}
export const fetchWorm = () => api<WormState>("/api/game/worm");
export const transferWorm = (userId: number) =>
  api<{ ok: boolean; status: string }>("/api/game/worm/transfer", {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });

export interface VoiceCurrent {
  enabled: boolean;
  task_id: number | null;
  title: string;
  text: string;
  reward: number;
  expires_at: string | null;
  my_submission_id: number | null;
  submissions: VoiceSubmission[];
}

export const fetchVoiceCurrent = () =>
  api<VoiceCurrent>("/api/game/voice/current");

export const withdrawVoice = () =>
  api<{ ok: boolean; status: string; reward: number }>(
    "/api/game/voice/submission",
    { method: "DELETE" },
  );

/**
 * Сдать голосовое. Запись уже приведена к формату Telegram (OGG/OPUS, M4A или
 * MP3 — см. `lib/voiceFormat`), файл не храним: сервер перешлёт его боту и
 * заберёт `file_id`. `filename` важен — Telegram смотрит на расширение.
 */
export async function uploadVoice(
  blob: Blob,
  duration: number,
  filename: string = "voice.ogg",
): Promise<{ ok: boolean; status: string; reward: number; detail?: string | null }> {
  const form = new FormData();
  form.append("file", blob, filename);
  form.append("duration", String(Math.max(0, Math.round(duration))));
  const res = await fetch(`${API_BASE}/api/game/voice/submit`, {
    method: "POST",
    headers: { Authorization: `tma ${getInitData()}` },
    body: form,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json();
}

/**
 * Прослушать вариант: тянем аудио с Authorization и отдаём blob-URL (элемент
 * `<audio>` не умеет отправлять заголовки сам). URL нужно освобождать.
 */
export async function fetchVoiceAudioUrl(id: number): Promise<string> {
  const res = await fetch(`${API_BASE}/api/game/voice/submissions/${id}/audio`, {
    headers: { Authorization: `tma ${getInitData()}` },
  });
  if (!res.ok) throw new Error("audio_unavailable");
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/**
 * GHG11(6): прослушать трек подборки, загруженный в бота (а не ссылкой).
 *
 * У таких треков есть только Telegram `file_id`, поэтому звук тянем блобом с
 * Authorization — тем же путём, что и голосовые сдачи. Для треков-ссылок этот
 * роут не нужен: они открываются по `url` на своём источнике.
 */
export async function fetchMusicAudioUrl(trackId: number): Promise<string> {
  const res = await fetch(`${API_BASE}/api/game/music/tracks/${trackId}/audio`, {
    headers: { Authorization: `tma ${getInitData()}` },
  });
  if (!res.ok) throw new Error("audio_unavailable");
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export const addMusicTrack = (body: {
  url: string;
  title?: string;
  performer?: string;
}) =>
  api<{ ok: boolean; status: string; week_count: number }>(
    "/api/game/music/tracks",
    { method: "POST", body: JSON.stringify(body) },
  );

/** Э15/Э16: «Предложка недели» — свои треки, лимит и история подборок. */
export interface MusicMineTrack {
  id: number;
  kind: string;
  title: string | null;
  performer: string | null;
  url: string | null;
  status: string;
  added_at: string | null;
}

export interface MusicSelection {
  id: number;
  tg_message_id: number | null;
  track_count: number;
  note: string | null;
  created_at: string | null;
}

/** Э17: трек выпущенной подборки с лайками. */
export interface MusicWeekTrack {
  id: number;
  kind: string;
  title: string | null;
  performer: string | null;
  url: string | null;
  likes: number;
  liked: boolean;
}

/** Э17: свежая подборка недели с треками и лайками. */
export interface MusicWeek {
  id: number;
  created_at: string | null;
  track_count: number;
  tracks: MusicWeekTrack[];
}

/** Э17: строка топа недели — трек и его лайки. */
export interface MusicTopTrack {
  id: number;
  title: string | null;
  performer: string | null;
  url: string | null;
  likes: number;
}

export interface MusicLikeResult {
  ok: boolean;
  liked: boolean;
  likes: number;
}

export interface MusicMine {
  enabled: boolean;
  per_user_weekly: number;
  week_count: number;
  tracks: MusicMineTrack[];
  history: MusicSelection[];
  /** Э17: свежая подборка с лайками + топ недели. */
  week: MusicWeek | null;
  top: MusicTopTrack[];
}

export const fetchMyMusic = () => api<MusicMine>("/api/game/music/mine");

/** Э17: поставить/снять лайк треку подборки (toggle на сервере). */
export const likeMusicTrack = (trackId: number) =>
  api<MusicLikeResult>(`/api/game/music/tracks/${trackId}/like`, {
    method: "POST",
  });

/** Э10.3: праздник — ежегодная дата + текст поздравления. */
export interface GameHoliday {
  id: number;
  month: number;
  day: number;
  message: string;
  enabled: boolean;
}

export interface GameHolidays {
  /** С 6 ранга или админу-отладчику; остальным — только чтение. */
  can_manage: boolean;
  required_level: number | null;
  items: GameHoliday[];
}

export const fetchHolidays = () => api<GameHolidays>("/api/game/holidays");

export const createHoliday = (month: number, day: number, message: string) =>
  api<GameHoliday>("/api/game/holidays", {
    method: "POST",
    body: JSON.stringify({ month, day, message }),
  });

export const deleteHoliday = (holidayId: number) =>
  api<void>(`/api/game/holidays/${holidayId}`, { method: "DELETE" });

/** Э11: подарок опыта имениннику (100 XP со своего счёта, раз в год на человека). */
export interface DonationResult {
  ok: boolean;
  code: string;
  amount: number;
  donor_xp: number;
  recipient_xp: number;
  recipient_name: string;
}

/**
 * `userId` — ВНУТРЕННИЙ id участника (как в `/api/users` и поповере ДР), а не
 * TG-id: мини-апп работает с участниками по своему id. Сервер принимает оба.
 */
export const donateXp = (userId: number) =>
  api<DonationResult>("/api/game/donate", {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
