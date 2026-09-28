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

export interface AchievementHolder {
  user_id: number;
  count: number;
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

export const fetchAchievementsChart = () =>
  api<AchievementHolder[]>("/api/game/achievements");

export const fetchRanksChart = () => api<RankRow[]>("/api/game/ranks");

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
