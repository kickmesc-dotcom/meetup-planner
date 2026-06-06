import { create } from "zustand";

/**
 * Восемь уровней зума по аналогии с iOS Calendar: от часовой шкалы одного
 * дня до общего обзора всех годов. Все уровни делятся на «полосовые»
 * (одна горизонтальная лента ячеек на участника — hour/day/week) и
 * «сеточные» (классическая календарная сетка — month/threeMonths/sixMonths/year/allYears).
 *
 * GHG6 CL0: уровень `twoWeeks` удалён в рамках подготовки к новому
 * TimelineView. Дефолт — `week`. Если позже захочется «произвольный
 * диапазон», добавим его отдельным presetom внутри TimelineView (CL12).
 */
export type ZoomLevel =
  | "hour"
  | "day"
  | "week"
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
  "week",
  "day",
  "hour",
];

export const ZOOM_LABELS: Record<ZoomLevel, string> = {
  hour: "Часы",
  day: "День",
  week: "Неделя",
  month: "Месяц",
  threeMonths: "3 мес",
  sixMonths: "Полгода",
  year: "Год",
  allYears: "Все годы",
};

export function isStripZoom(z: ZoomLevel): boolean {
  return z === "day" || z === "week";
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

  /**
   * GHG6 BD2: поповер «🎂 поздравить / назначить встречу». Хранит, чьё ДР
   * и на какую дату открыто. Закрывается через setBirthdayPopover(null).
   */
  birthdayPopover: { userId: number; date: string; displayName: string } | null;
  setBirthdayPopover: (v: { userId: number; date: string; displayName: string } | null) => void;

  /**
   * GHG7 P0.2.e: попап с причиной ролла по клику на корону 👑.
   * userId — кому корона, date — день (YYYY-MM-DD), displayName — имя для
   * заголовка. Закрывается через setLoserReasonPopover(null).
   */
  loserReasonPopover: { userId: number; date: string; displayName: string } | null;
  setLoserReasonPopover: (v: { userId: number; date: string; displayName: string } | null) => void;

  /**
   * GHG6 BD2: дата, с которой надо открыть PollSheet при «Назначить встречу»
   * из поповера. PollSheet читает её при монтаже и кладёт в первый вариант.
   */
  pollSheetPresetDate: string | null;
  setPollSheetPresetDate: (date: string | null) => void;

  /**
   * GHG8 P2.4.c: предзаполненный вопрос опроса при открытии PollSheet из
   * ДР-поповера («Собираемся на ДР {имя}?»). Очищается вместе с presetDate.
   */
  pollSheetPresetQuestion: string | null;
  setPollSheetPresetQuestion: (q: string | null) => void;

  /**
   * GHG6 P3 CL5: пользовательский cellWidth для TimelineView. null = «авто»
   * (TimelineView сам считает по ResizeObserver — CL6.a). Когда пользователь
   * двинул слайдер зума или нажал пресет «День»/«Неделя»/«Месяц», сюда
   * кладётся фиксированное значение в px и TimelineView читает его.
   */
  timelineCellWidth: number | null;
  setTimelineCellWidth: (w: number | null) => void;
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

  zoom: "week",
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

  birthdayPopover: null,
  setBirthdayPopover: (birthdayPopover) => set({ birthdayPopover }),

  loserReasonPopover: null,
  setLoserReasonPopover: (loserReasonPopover) => set({ loserReasonPopover }),

  pollSheetPresetDate: null,
  setPollSheetPresetDate: (pollSheetPresetDate) => set({ pollSheetPresetDate }),

  pollSheetPresetQuestion: null,
  setPollSheetPresetQuestion: (pollSheetPresetQuestion) =>
    set({ pollSheetPresetQuestion }),

  timelineCellWidth: null,
  setTimelineCellWidth: (timelineCellWidth) => set({ timelineCellWidth }),
}));
