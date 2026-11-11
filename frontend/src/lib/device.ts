/**
 * Откуда человек смотрит приложение: телефон, компьютер или обычный браузер.
 *
 * Вынесено отдельно от `vitals.ts`, чтобы и телеметрия ошибок, и RUM
 * описывали устройство одинаково, а импорт не ходил по кругу
 * (`telemetry` → `vitals` → `telemetry`).
 */
import { WebApp } from "@/tg/webapp";

export type DeviceKind = "mobile" | "desktop" | "web";

const MAX_PLATFORM = 20;

/**
 * Сначала спрашиваем Telegram: `platform` — `android`, `ios`, `tdesktop`,
 * `macos`, `web`. По нему видно мини-апп на телефоне, а не «узкое окно на
 * мониторе», что важно: у них разные причины тормозов. Вне Telegram остаётся
 * ширина экрана — грубая, но честная оценка.
 */
export function deviceKind(): DeviceKind {
  try {
    const platform = String(WebApp.platform ?? "");
    if (platform === "android" || platform === "ios") return "mobile";
    if (platform === "tdesktop" || platform === "macos" || platform === "unigram") {
      return "desktop";
    }
  } catch {
    // вне Telegram — ниже
  }
  if (typeof window === "undefined" || typeof window.innerWidth !== "number") {
    return "web";
  }
  return window.innerWidth < 768 ? "mobile" : "desktop";
}

/** Платформа клиента для отчёта; пусто вне Telegram. */
export function platformName(): string {
  try {
    return String(WebApp.platform ?? "").slice(0, MAX_PLATFORM);
  } catch {
    return "";
  }
}

/** Версия Bot API в клиенте — по ней видно, какие методы человеку доступны. */
export function tgVersion(): string {
  try {
    return String(WebApp.version ?? "").slice(0, MAX_PLATFORM);
  } catch {
    return "";
  }
}
