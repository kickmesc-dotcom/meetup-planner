import WebApp from "@twa-dev/sdk";

let initialized = false;

export function initTelegramWebApp(): void {
  if (initialized) return;
  initialized = true;
  try {
    WebApp.ready();
    WebApp.expand();
    WebApp.disableVerticalSwipes?.();
  } catch {
    // outside Telegram (local dev) — ok
  }
}

export function getInitData(): string {
  // Inside Telegram, WebApp.initData is the raw query string we send to backend.
  return WebApp.initData ?? "";
}

export type HapticKind =
  | "light"
  | "medium"
  | "heavy"
  | "rigid"
  | "soft"
  | "success"
  | "error"
  | "warning"
  | "selection";

export function haptic(kind: HapticKind = "light"): void {
  try {
    if (kind === "success" || kind === "error" || kind === "warning") {
      WebApp.HapticFeedback.notificationOccurred(kind);
    } else if (kind === "selection") {
      WebApp.HapticFeedback.selectionChanged();
    } else {
      WebApp.HapticFeedback.impactOccurred(kind);
    }
  } catch {
    // no-op (outside Telegram)
  }
}

export { WebApp };
