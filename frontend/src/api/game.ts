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
