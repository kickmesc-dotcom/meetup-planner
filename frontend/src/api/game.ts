import { api } from "./client";

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
  prestige: number;
  supreme: boolean;
  completionist: boolean;
  loser_count: number;
  chukhan_count: number;
  rank_position: number | null;
  ranks_total: number;
  achievements_collected: number;
  achievements_total: number;
  achievements: GuestAchievement[];
}

/** Э19: профиль участника по внутреннему id (клик по аватарке на календаре). */
export const fetchGuestProfile = (userId: number) =>
  api<GuestProfile>(`/api/game/players/${userId}`);

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
}

export interface GameFeed {
  enabled: boolean;
  items: FeedItem[];
  next_offset: number | null;
  /** Э21: доступные типы записей — для чипов-фильтров. */
  kinds: string[];
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
};

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
