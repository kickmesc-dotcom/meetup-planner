import { create } from "zustand";

/**
 * Девять уровней зума по аналогии с iOS Calendar: от часовой шкалы одного
 * дня до общего обзора всех годов. Все уровни делятся на «полосовые»
 * (одна горизонтальная лента ячеек на участника — hour/day/week/twoWeeks)
 * и «сеточные» (классическая календарная сетка — month/threeMonths/sixMonths/year/allYears).
 */
export type ZoomLevel =
  | "hour"
  | "day"
  | "week"
  | "twoWeeks"
  | "month"
  | "threeMonths"
  | "sixMonths"
  | "year"
  | "allYears";

export const ZOOM_ORDER: ZoomLevel[] = [
  "allYears",
  "year",
  "sixMonths",
  "threeMonths",
  "month",
  "twoWeeks",
  "week",
  "day",
  "hour",
];

export const ZOOM_LABELS: Record<ZoomLevel, string> = {
  hour: "Часы",
  day: "День",
  week: "Неделя",
  twoWeeks: "2 нед",
  month: "Месяц",
  threeMonths: "3 мес",
  sixMonths: "Полгода",
  year: "Год",
  allYears: "Все годы",
};

export function isStripZoom(z: ZoomLevel): boolean {
  return z === "day" || z === "week" || z === "twoWeeks";
}

export function isMonthGridZoom(z: ZoomLevel): boolean {
  return z === "month" || z === "threeMonths" || z === "sixMonths";
}

export type Tab = "calendar" | "meetings" | "polls" | "leaderboard" | "admin";

interface UIState {
  tab: Tab;
  setTab: (t: Tab) => void;

  zoom: ZoomLevel;
  setZoom: (z: ZoomLevel) => void;
  zoomIn: () => void;
  zoomOut: () => void;

  /** Дата, вокруг которой строится текущий вид. */
  anchorDate: Date;
  setAnchorDate: (d: Date) => void;
  /** Сдвиг anchor на N единиц текущего zoom-уровня (вперёд/назад). */
  shiftAnchor: (direction: 1 | -1) => void;
  /** Прыжок к сегодня. */
  goToday: () => void;

  editingRangeId: number | "new" | null;
  setEditingRangeId: (v: number | "new" | null) => void;

  showAutoPickSheet: boolean;
  setShowAutoPickSheet: (v: boolean) => void;

  showLoserSheet: boolean;
  setShowLoserSheet: (v: boolean) => void;

  showPollSheet: boolean;
  setShowPollSheet: (v: boolean) => void;
}

function shiftDateByZoom(d: Date, z: ZoomLevel, dir: 1 | -1): Date {
  const x = new Date(d);
  switch (z) {
    case "hour":
    case "day":
      x.setDate(x.getDate() + dir);
      break;
    case "week":
      x.setDate(x.getDate() + dir * 7);
      break;
    case "twoWeeks":
      x.setDate(x.getDate() + dir * 14);
      break;
    case "month":
      x.setMonth(x.getMonth() + dir);
      break;
    case "threeMonths":
      x.setMonth(x.getMonth() + dir * 3);
      break;
    case "sixMonths":
      x.setMonth(x.getMonth() + dir * 6);
      break;
    case "year":
      x.setFullYear(x.getFullYear() + dir);
      break;
    case "allYears":
      x.setFullYear(x.getFullYear() + dir * 10);
      break;
  }
  return x;
}

export const useUI = create<UIState>((set, get) => ({
  tab: "calendar",
  setTab: (tab) => set({ tab }),

  zoom: "twoWeeks",
  setZoom: (zoom) => set({ zoom }),
  zoomIn: () => {
    const cur = get().zoom;
    const i = ZOOM_ORDER.indexOf(cur);
    if (i < ZOOM_ORDER.length - 1) set({ zoom: ZOOM_ORDER[i + 1] });
  },
  zoomOut: () => {
    const cur = get().zoom;
    const i = ZOOM_ORDER.indexOf(cur);
    if (i > 0) set({ zoom: ZOOM_ORDER[i - 1] });
  },

  anchorDate: new Date(),
  setAnchorDate: (anchorDate) => set({ anchorDate }),
  shiftAnchor: (dir) =>
    set({ anchorDate: shiftDateByZoom(get().anchorDate, get().zoom, dir) }),
  goToday: () => set({ anchorDate: new Date() }),

  editingRangeId: null,
  setEditingRangeId: (editingRangeId) => set({ editingRangeId }),

  showAutoPickSheet: false,
  setShowAutoPickSheet: (v) => set({ showAutoPickSheet: v }),

  showLoserSheet: false,
  setShowLoserSheet: (v) => set({ showLoserSheet: v }),

  showPollSheet: false,
  setShowPollSheet: (v) => set({ showPollSheet: v }),
}));
