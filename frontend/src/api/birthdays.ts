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
export interface CalendarMark {
  date: string; // YYYY-MM-DD
  user_id: number;
  type: "loser" | "chukhan";
}

export const fetchCalendarMarks = (from: Date, to: Date) =>
  api<CalendarMark[]>(
    `/api/calendar/marks?from=${from.toISOString()}&to=${to.toISOString()}`,
  );
