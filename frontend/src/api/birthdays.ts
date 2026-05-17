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
