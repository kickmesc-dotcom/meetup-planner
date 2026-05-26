import {
  addDays,
  addHours,
  addMonths,
  differenceInCalendarDays,
  endOfMonth,
  endOfWeek,
  startOfDay,
  startOfMonth,
  startOfWeek,
  startOfYear,
} from "date-fns";

import type { ZoomLevel } from "@/store/ui";

export const DAY_MS = 24 * 60 * 60 * 1000;
export const HOUR_MS = 60 * 60 * 1000;

/** Понедельник как первый день недели — соответствует ru-локали. */
export const WEEK_OPTS = { weekStartsOn: 1 } as const;

export function buildDaysWindow(start: Date, span: number): Date[] {
  const s = startOfDay(start);
  return Array.from({ length: span }, (_, i) => addDays(s, i));
}

export function buildHoursWindow(day: Date): Date[] {
  const s = startOfDay(day);
  return Array.from({ length: 24 }, (_, i) => addHours(s, i));
}

/** 6×7=42 ячейки сетки месяца, начиная с понедельника недели, в которую
 * попадает первое число. Не пересчитывает: всегда возвращает 42 даты, чтобы
 * высота сетки не прыгала между месяцами. */
export function buildMonthGrid(monthAnchor: Date): Date[] {
  const first = startOfMonth(monthAnchor);
  const gridStart = startOfWeek(first, WEEK_OPTS);
  return Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
}

/**
 * Окно дат для текущего zoom-уровня вокруг anchor.
 * Возвращает [start, end) — end эксклюзивный.
 */
export function windowForZoom(zoom: ZoomLevel, anchor: Date): { start: Date; end: Date } {
  const a = startOfDay(anchor);
  switch (zoom) {
    case "hour":
    case "day":
      return { start: a, end: addDays(a, 1) };
    case "week": {
      const start = startOfWeek(a, WEEK_OPTS);
      return { start, end: addDays(start, 7) };
    }
    case "month": {
      const start = startOfMonth(a);
      return { start, end: addDays(endOfMonth(start), 1) };
    }
    case "threeMonths": {
      const start = startOfMonth(addMonths(a, -1));
      return { start, end: addDays(endOfMonth(addMonths(start, 2)), 1) };
    }
    case "sixMonths": {
      const start = startOfMonth(addMonths(a, -2));
      return { start, end: addDays(endOfMonth(addMonths(start, 5)), 1) };
    }
    case "year": {
      const start = startOfYear(a);
      const end = new Date(start);
      end.setFullYear(end.getFullYear() + 1);
      return { start, end };
    }
    case "allYears": {
      const yr = a.getFullYear();
      const decade = yr - (yr % 10);
      const start = new Date(decade, 0, 1);
      const end = new Date(decade + 10, 0, 1);
      return { start, end };
    }
  }
}

export interface PillRect {
  startIndex: number;
  span: number;
  clippedLeft: boolean;
  clippedRight: boolean;
}

export function rangeToPillRect(
  startsAt: Date,
  endsAt: Date,
  windowStart: Date,
  windowSpan: number,
): PillRect | null {
  const startDay = startOfDay(windowStart);
  const startIdx = differenceInCalendarDays(startsAt, startDay);
  const endIdxInclusive = differenceInCalendarDays(
    new Date(endsAt.getTime() - 1),
    startDay,
  );

  if (endIdxInclusive < 0) return null;
  if (startIdx >= windowSpan) return null;

  const clippedLeft = startIdx < 0;
  const clippedRight = endIdxInclusive >= windowSpan;

  const visibleStart = Math.max(0, startIdx);
  const visibleEndInc = Math.min(windowSpan - 1, endIdxInclusive);

  return {
    startIndex: visibleStart,
    span: visibleEndInc - visibleStart + 1,
    clippedLeft,
    clippedRight,
  };
}

export function rangeToHourRect(
  startsAt: Date,
  endsAt: Date,
  day: Date,
): PillRect | null {
  const dayStart = startOfDay(day).getTime();
  const dayEnd = dayStart + DAY_MS;
  const s = startsAt.getTime();
  const e = endsAt.getTime();
  if (e <= dayStart || s >= dayEnd) return null;

  const visStart = Math.max(s, dayStart);
  const visEnd = Math.min(e, dayEnd);

  return {
    startIndex: (visStart - dayStart) / HOUR_MS,
    span: (visEnd - visStart) / HOUR_MS,
    clippedLeft: s < dayStart,
    clippedRight: e > dayEnd,
  };
}

/** Day-status-summary для одной ячейки в month/year сетке.
 * Возвращает { free, maybe, busy } — сколько участников из ranges имеют такой
 * статус на эту дату хотя бы по одному range. */
export function summarizeDay(
  day: Date,
  ranges: { user_id: number; starts_at: string; ends_at: string; status: 1 | 2 | 3 }[],
): { free: number; maybe: number; busy: number; total: number } {
  const dayStart = startOfDay(day).getTime();
  const dayEnd = dayStart + DAY_MS;
  const buckets: Record<1 | 2 | 3, Set<number>> = {
    1: new Set(),
    2: new Set(),
    3: new Set(),
  };
  for (const r of ranges) {
    const s = new Date(r.starts_at).getTime();
    const e = new Date(r.ends_at).getTime();
    if (e <= dayStart || s >= dayEnd) continue;
    buckets[r.status].add(r.user_id);
  }
  return {
    free: buckets[1].size,
    maybe: buckets[2].size,
    busy: buckets[3].size,
    total: buckets[1].size + buckets[2].size + buckets[3].size,
  };
}

export function statusColor(status: 1 | 2 | 3): string {
  switch (status) {
    case 1:
      return "#22c55e";
    case 2:
      return "#f59e0b";
    case 3:
      return "#ef4444";
  }
}

export function statusLabel(s: 1 | 2 | 3): string {
  return s === 1 ? "свободен" : s === 2 ? "может" : "занят";
}

/**
 * GHG6 CL7: цвет заливки TimelineCell по status × confidence.
 *
 * Семантика статусов (как в `summarizeDay`/`statusLabel`): 1=свободен, 2=может,
 * 3=занят. Worst-status на день: 3 > 2 > 1 (занят бьёт всё — это худший исход
 * для координации встречи; «может» хуже «свободен», но лучше «занят»).
 *
 * Шкала confidence (1..5) модулирует, насколько мы доверяем заявленному статусу:
 * - status=1 (свободен): conf 5 → насыщенный зелёный («точно свободен»),
 *   conf 1 → красный («заявил свободен, но уверенность нулевая → по факту занят»).
 * - status=3 (занят, инверсия): conf 5 → насыщенный красный, conf 1 → зелёный.
 * - status=2 (может): жёлтый с opacity по confidence (3 → средний, 5 → плотный,
 *   1 → бледный).
 *
 * Возвращает CSS `background` строку (Tailwind-цвета как hex/rgba — Tailwind
 * arbitrary-value классы в runtime'е не работают, нужен inline style).
 *
 * Если на день нет range — возвращает null (caller рисует серый «не отмечено»
 * паттерн, как было до CL7).
 *
 * GHG6 CL9: для worst-range при `all_day=false` возвращает дополнительно
 * `partial`: top/height в долях [0..1] относительно ячейки (top=0 — верх ячейки
 * = 0:00 локальных суток, height=1 — на весь день). Caller рисует частичную
 * полосу заливки вместо полной. Если worst-range `all_day=true` (либо поле
 * отсутствует — для обратной совместимости считаем полным днём), `partial=null`.
 */
export interface DayFill {
  background: string;
  status: 1 | 2 | 3;
  confidence: number;
  /** null = полная заливка ячейки (all_day=true). Иначе — позиционная полоса
   * по доле дня worst-range'а. */
  partial: { top: number; height: number } | null;
}

export function confidenceFillForDay(
  day: Date,
  ranges: {
    starts_at: string;
    ends_at: string;
    status: 1 | 2 | 3;
    confidence: number;
    all_day?: boolean;
  }[],
): DayFill | null {
  const dayStart = startOfDay(day).getTime();
  const dayEnd = dayStart + DAY_MS;

  // Worst-status агрегация: 3 > 2 > 1. Для итогового цвета берём максимальную
  // confidence среди range'ей с worst-status — чем увереннее «худший» голос,
  // тем темнее цвет.
  // GHG6 CL9: одновременно с цветом отслеживаем сам range, выигравший
  // worst-status (нужны его `starts_at`/`ends_at`/`all_day` для partial-fraction).
  let worst: 0 | 1 | 2 | 3 = 0;
  let worstConf = 0;
  let worstRange: (typeof ranges)[number] | null = null;
  for (const r of ranges) {
    const s = new Date(r.starts_at).getTime();
    const e = new Date(r.ends_at).getTime();
    if (e <= dayStart || s >= dayEnd) continue;
    if (r.status > worst) {
      worst = r.status;
      worstConf = r.confidence;
      worstRange = r;
    } else if (r.status === worst) {
      if (r.confidence > worstConf) {
        worstConf = r.confidence;
        worstRange = r;
      } else if (r.confidence === worstConf) {
        // GHG6 CL9: при равных status и confidence предпочитаем all_day=true —
        // полная заливка точнее отражает реальное покрытие дня.
        if (r.all_day === true && worstRange && worstRange.all_day !== true) {
          worstRange = r;
        }
      }
    }
  }
  if (worst === 0 || worstRange === null) return null;

  const conf = clamp(worstConf, 1, 5);
  // GHG6 CL9: partial — только если worst-range явно НЕ all_day. Старые
  // записи без поля считаем полным днём (обратная совместимость).
  let partial: { top: number; height: number } | null = null;
  if (worstRange.all_day === false) {
    const s = new Date(worstRange.starts_at).getTime();
    const e = new Date(worstRange.ends_at).getTime();
    const visStart = Math.max(s, dayStart);
    const visEnd = Math.min(e, dayEnd);
    const top = clamp((visStart - dayStart) / DAY_MS, 0, 1);
    const height = clamp((visEnd - visStart) / DAY_MS, 0, 1);
    // Защита от нулевой полосы — лучше показать full-fill, чем «пустой» day.
    if (height > 0) {
      partial = { top, height };
    }
  }

  return {
    background: pickConfidenceColor(worst, conf),
    status: worst,
    confidence: conf,
    partial,
  };
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/**
 * Цветовая шкала status × confidence. Источник палитры — Tailwind 500/400/300:
 * green-500 = #22c55e, green-400 = #4ade80, gray-300 = #d1d5db,
 * red-400 = #f87171, red-500 = #ef4444, amber-400 = #fbbf24.
 *
 * Промежуточные ступени (conf 4 и conf 2) для status 1/3 берут «противоположный»
 * 400-й оттенок с opacity 0.6 — это создаёт ощущение «склоняется в сторону X, но
 * не уверенно». Для status=2 (может) — амбер с opacity по confidence.
 */
function pickConfidenceColor(status: 1 | 2 | 3, confidence: number): string {
  if (status === 1) {
    // свободен → зелёные тона при высокой уверенности, красные при низкой.
    switch (confidence) {
      case 5: return "#22c55e";                  // green-500 solid
      case 4: return "rgba(74,222,128,0.6)";     // green-400/60
      case 3: return "#d1d5db";                  // gray-300 — баланс
      case 2: return "rgba(248,113,113,0.6)";    // red-400/60
      case 1: return "#ef4444";                  // red-500 solid
    }
  }
  if (status === 3) {
    // занят → инверсия: высокая уверенность = насыщенный красный.
    switch (confidence) {
      case 5: return "#ef4444";
      case 4: return "rgba(248,113,113,0.6)";
      case 3: return "#d1d5db";
      case 2: return "rgba(74,222,128,0.6)";
      case 1: return "#22c55e";
    }
  }
  // status === 2 (может) — жёлтая шкала с opacity по confidence.
  // conf 5 → плотный, conf 1 → почти прозрачный (но не пустой, иначе ячейка
  // визуально слипнется с «не отмечено»).
  const opacity = 0.25 + ((confidence - 1) / 4) * 0.65; // 0.25..0.9
  return `rgba(251,191,36,${opacity.toFixed(2)})`;       // amber-400
}

/** Короткое читаемое сокращение для пилюли/ячейки.
 * Никаких «сво…» и «з…» — слово целиком либо нормальное сокращение. */
export function statusLabelShort(s: 1 | 2 | 3): string {
  return s === 1 ? "своб." : s === 2 ? "может" : "зан.";
}

/** Вспомогательный: «1 апреля» или «1 апр» в ru-локали без подключения локали
 * для year-grid (там нужно строго коротко). */
const RU_MONTHS_SHORT = [
  "янв", "фев", "мар", "апр", "май", "июн",
  "июл", "авг", "сен", "окт", "ноя", "дек",
];
const RU_MONTHS_FULL = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];
const RU_WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

export function ruMonthShort(monthIndex: number): string {
  return RU_MONTHS_SHORT[monthIndex] ?? "";
}
export function ruMonthFull(monthIndex: number): string {
  return RU_MONTHS_FULL[monthIndex] ?? "";
}
export function ruWeekdayShort(dayOfWeek: number): string {
  // date-fns getDay(): 0=вс, 1=пн … — а нам нужно индекс при weekStartsOn=пн.
  return RU_WEEKDAYS_SHORT[(dayOfWeek + 6) % 7] ?? "";
}

/** Заголовок текущего вида для NavBar: «8 мая 2026 · пятница», «Май 2026», «2026» и т.д. */
export function zoomTitle(zoom: ZoomLevel, anchor: Date): string {
  const a = anchor;
  switch (zoom) {
    case "hour":
    case "day": {
      const dow = ruWeekdayShort(a.getDay());
      return `${a.getDate()} ${ruMonthShort(a.getMonth())} ${a.getFullYear()} · ${dow}`;
    }
    case "week": {
      const ws = startOfWeek(a, WEEK_OPTS);
      const we = endOfWeek(a, WEEK_OPTS);
      const sameMonth = ws.getMonth() === we.getMonth();
      if (sameMonth) {
        return `${ws.getDate()}–${we.getDate()} ${ruMonthShort(ws.getMonth())} ${ws.getFullYear()}`;
      }
      return `${ws.getDate()} ${ruMonthShort(ws.getMonth())} – ${we.getDate()} ${ruMonthShort(we.getMonth())} ${we.getFullYear()}`;
    }
    case "month":
      return `${ruMonthFull(a.getMonth())} ${a.getFullYear()}`;
    case "threeMonths":
    case "sixMonths": {
      const w = windowForZoom(zoom, a);
      const last = addDays(w.end, -1);
      return `${ruMonthShort(w.start.getMonth())} – ${ruMonthShort(last.getMonth())} ${last.getFullYear()}`;
    }
    case "year":
      return `${a.getFullYear()}`;
    case "allYears": {
      const yr = a.getFullYear();
      const decade = yr - (yr % 10);
      return `${decade} – ${decade + 9}`;
    }
  }
}
