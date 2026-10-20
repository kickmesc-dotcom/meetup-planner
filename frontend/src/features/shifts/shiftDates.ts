/**
 * Даты табеля: неделя начинается с понедельника, дни — локальные.
 *
 * Вынесено из `ShiftsScreen`, когда появился шаблон недели: экран и лист
 * массовых операций должны считать «пн-ср» одинаково, иначе шаблон уезжал бы
 * на день. Никаких UTC-преобразований: `toIso` пишет локальную дату, потому что
 * сервер хранит `Date` без времени.
 */

export function mondayOf(date: Date): Date {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  const shift = (copy.getDay() + 6) % 7;
  copy.setDate(copy.getDate() - shift);
  return copy;
}

export function addDays(date: Date, days: number): Date {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

export function toIso(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** 0 = понедельник … 6 = воскресенье (индекс дня в неделе). */
export function weekdaysToIso(weekStart: Date, weekdays: number[]): string[] {
  return [...new Set(weekdays)]
    .filter((day) => day >= 0 && day <= 6)
    .sort((a, b) => a - b)
    .map((day) => toIso(addDays(weekStart, day)));
}

export function cellKey(employeeId: number, day: string): string {
  return `${employeeId}:${day}`;
}

export function weekday(date: Date): string {
  return date.toLocaleDateString("ru-RU", { weekday: "short" }).slice(0, 2);
}

export function formatDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

export function rangeLabel(days: Date[]): string {
  const first = days[0];
  const last = days[days.length - 1];
  const sameMonth = first.getMonth() === last.getMonth();
  const left = first.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
  });
  const right = last.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: sameMonth ? undefined : "short",
    year: last.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  });
  return `${left} — ${right}`;
}
