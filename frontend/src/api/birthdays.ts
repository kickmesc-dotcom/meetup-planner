import { api } from "./client";

export interface BirthdayCalendarEntry {
  user_id: number;
  display_name: string;
  date: string; // YYYY-MM-DD — реальная дата в окне (для 29.02 в невис. году = 28.02)
  bday: string; // YYYY-MM-DD — исходная дата
  year_known: boolean;
}

export const fetchBirthdaysInWindow = (from: Date, to: Date) =>
  api<BirthdayCalendarEntry[]>(
    `/api/birthdays/calendar?from=${from.toISOString()}&to=${to.toISOString()}`,
  );

// GHG6 BD2: креативное поздравление по шаблону (без LLM, шаблоны в admin_config).
export interface BirthdayGreeting {
  text: string;
  template_index: number;
}

export const fetchBirthdayGreeting = (userId: number, date: string) =>
  api<BirthdayGreeting>(
    `/api/birthdays/${userId}/greeting?date=${encodeURIComponent(date)}`,
    { method: "POST" },
  );

// GHG8 P2.4: публикация поздравления в группу от лица бота.
// signed=true → бот допишет «— Поздравил {имя нажавшего}» (режим «от своего
// имени»: TG не даёт постить за юзера, подпись — честная замена).
export interface GreetingPostResult {
  ok: boolean;
  signed: boolean;
}

export const postBirthdayGreeting = (
  userId: number,
  text: string,
  signed: boolean,
) =>
  api<GreetingPostResult>(`/api/birthdays/${userId}/greeting/post`, {
    method: "POST",
    body: JSON.stringify({ text, signed }),
  });

// GHG6 BD4: отметки лох/чухан в окне (для рисования 👑/💩 в ячейках).
// GHG6 J: для type='loser' приходит source ('auto' | 'manual'). Один и тот же
// день у одного юзера может содержать обе метки — фронт рисует 👑×2.
// Для type='chukhan' source всегда null.
export interface CalendarMark {
  date: string; // YYYY-MM-DD
  user_id: number;
  type: "loser" | "chukhan";
  // GHG7 P9.4.a: auto/manual → 👑 «Лох дня», duel → 🤡 «Автолох» (ручная дуэль).
  source?: "auto" | "manual" | "duel" | null;
}

export const fetchCalendarMarks = (from: Date, to: Date) =>
  api<CalendarMark[]>(
    `/api/calendar/marks?from=${from.toISOString()}&to=${to.toISOString()}`,
  );

// GHG7 P0.2.e: попап «причина ролла» по клику на корону. Возвращает
// последний роллов день/юзер — если их несколько, берём rolled_at DESC.
// 404 — корона нарисована, а записи нет (cache mismatch).
export interface LoserReason {
  rolled_at: string; // ISO
  reason_text: string | null;
  source: "auto" | "manual" | "duel" | null;
  rolled_by_name: string | null;
  was_worm: boolean;
}

export const fetchLoserReason = (day: string, userId: number) =>
  api<LoserReason>(
    `/api/calendar/loser/${encodeURIComponent(day)}/${userId}`,
  );

// GHG6 E8.4: активный «червь-пидор». Звание переходящее, одновременно ≤1.
// Все поля = null, если никого не назначено.
export interface WormCurrent {
  user_id: number | null;
  display_name: string | null;
  started_at: string | null;
}

export const fetchCurrentWorm = () =>
  api<WormCurrent>("/api/worm/current");

// GHG7 P2.1.a: актуальные звания для «шапки» аватарки. Каждое поле — user_id
// текущего носителя (или список), null/[] если носителя нет.
// GHG7 P10.1.e: после упрощения шапки фронт использует только worm/chukhan.
// loser_today/main_loser/birthday_today бэк по-прежнему отдаёт (API не трогаем),
// но ParticipantRow их больше НЕ читает — оставлены в типе как контракт ответа.
export interface CurrentTitles {
  worm_user_id: number | null;
  chukhan_user_id: number | null;
  loser_today_user_id: number | null;
  main_loser_user_id: number | null;
  /** GHG8 P4.1.a: сколько раз главный лох был лохом (0 если нет). */
  main_loser_count: number;
  birthday_today_user_ids: number[];
}

export const fetchCurrentTitles = () =>
  api<CurrentTitles>("/api/titles/current");

// GHG8 P4.1.e: публичная история чуханов (профиль). Только доставленные.
export interface ChukhanHistoryEntry {
  week_start: string; // ISO
  user_id: number;
  posted_at: string; // ISO
}

export const fetchChukhanHistory = (limit = 20) =>
  api<ChukhanHistoryEntry[]>(`/api/chukhan/history?limit=${limit}`);

// GHG8 P2.1.c: публичная история «червей-пидоров» (worm_assignments).
// ended_at = null → текущий носитель звания.
export interface WormHistoryEntry {
  user_id: number;
  started_at: string; // ISO
  ended_at: string | null; // ISO | null (null = активный)
}

export const fetchWormHistory = (limit = 20) =>
  api<WormHistoryEntry[]>(`/api/worm/history?limit=${limit}`);

// GHG6 E6: запланированные игры (meeting.tag='game') в окне.
// Используется для иконки 🎮 в углу дня в CalendarView.
export interface GameSession {
  meeting_id: number;
  title: string;
  date: string; // YYYY-MM-DD
  starts_at: string; // ISO
}

export const fetchScheduledGames = (from: Date, to: Date) =>
  api<GameSession[]>(
    `/api/games/scheduled?from=${from.toISOString()}&to=${to.toISOString()}`,
  );
