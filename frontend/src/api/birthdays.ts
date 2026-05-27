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

// GHG6 BD4: отметки лох/чухан в окне (для рисования 👑/💩 в ячейках).
// GHG6 J: для type='loser' приходит source ('auto' | 'manual'). Один и тот же
// день у одного юзера может содержать обе метки — фронт рисует 👑×2.
// Для type='chukhan' source всегда null.
export interface CalendarMark {
  date: string; // YYYY-MM-DD
  user_id: number;
  type: "loser" | "chukhan";
  source?: "auto" | "manual" | null;
}

export const fetchCalendarMarks = (from: Date, to: Date) =>
  api<CalendarMark[]>(
    `/api/calendar/marks?from=${from.toISOString()}&to=${to.toISOString()}`,
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
