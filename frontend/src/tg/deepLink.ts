import type { Tab } from "@/store/ui";

/**
 * Диплинк из push в нужный раздел (MOBILE_PARALLEL, M3).
 *
 * Зачем отдельный модуль. Ссылку присылает сервер (`/?task=42`), её же
 * открывает service worker по тапу, и её же может принести `postMessage` в уже
 * открытое окно. Три места, один разбор: если правила разъедутся, тап по
 * уведомлению откроет корень — ровно то, от чего уходим.
 *
 * Почему только известные разделы. `?open=` приходит из уведомления, но
 * разбирает его клиент; неизвестное значение превратилось бы в пустой экран.
 * Белый список — это же и защита от «ссылка ведёт куда угодно».
 */

/** Разделы, куда можно прийти по ссылке из уведомления. */
export const DEEP_LINK_TABS: ReadonlySet<string> = new Set([
  "tasks",
  "feed",
  "checklist",
  "shifts",
  "issues",
  "handovers",
  "standards",
  "materials",
  "links",
  "profile",
  "ask",
]);

export interface DeepLink {
  tab: Tab;
  /** Номер поручения, если ссылка ведёт к задаче. */
  taskId: number | null;
  /** Номер проблемы, если ссылка ведёт в журнал к конкретной записи. */
  issueId: number | null;
}

/**
 * Разобрать адрес. Абсолютный и относительный — одинаково: service worker
 * присылает полный URL, `location` — относительный.
 */
export function parseDeepLink(raw: string): DeepLink | null {
  let url: URL;
  try {
    url = new URL(raw, "https://app.local");
  } catch {
    return null;
  }
  const taskRaw = url.searchParams.get("task");
  if (taskRaw !== null) {
    // Только цифры: `task=abc` — не задача, а мусор в адресе.
    if (!/^\d+$/.test(taskRaw)) return null;
    return { tab: "tasks", taskId: Number(taskRaw), issueId: null };
  }
  // §3 `deep-link`: уведомление о проблеме ведёт не в журнал вообще, а в ту
  // запись, из-за которой оно пришло.
  const issueRaw = url.searchParams.get("issue");
  if (issueRaw !== null) {
    if (!/^\d+$/.test(issueRaw)) return null;
    return { tab: "issues", taskId: null, issueId: Number(issueRaw) };
  }
  const open = url.searchParams.get("open");
  if (open && DEEP_LINK_TABS.has(open))
    return { tab: open as Tab, taskId: null, issueId: null };
  return null;
}

/** Ссылка из текущего адреса окна. */
export function deepLinkFromLocation(
  location: Pick<Location, "pathname" | "search"> = window.location,
): DeepLink | null {
  return parseDeepLink(`${location.pathname}${location.search}`);
}

/**
 * Убрать параметры из адресной строки после применения.
 *
 * Без этого повторный запуск приложения снова открывал бы задачу, хотя
 * человек уже ушёл с неё: адрес остался в истории и в ярлыке.
 */
export function clearDeepLink(): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (!url.search) return;
  url.search = "";
  window.history.replaceState({}, "", `${url.pathname}${url.hash}`);
}
