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
  installFocusScrollFix();
}

/**
 * iOS Telegram WebView: при появлении клавиатуры viewport "прыгает" вверх и
 * сфокусированный input уезжает из видимой области. Подсасываем его обратно
 * через scrollIntoView. Срабатывает и на focusin (мгновенно при тапе),
 * и на viewportChanged (когда WebApp выровнялся после открытия клавиатуры).
 */
function installFocusScrollFix(): void {
  const isEditable = (el: EventTarget | null): el is HTMLElement => {
    if (!(el instanceof HTMLElement)) return false;
    const tag = el.tagName;
    if (tag === "INPUT") {
      const t = (el as HTMLInputElement).type;
      // datetime-local/date/time на iOS открывают пикер, не клавиатуру — пропускаем.
      if (t === "date" || t === "time" || t === "datetime-local" || t === "month" || t === "week") {
        return false;
      }
      return true;
    }
    if (tag === "TEXTAREA") return true;
    return el.isContentEditable;
  };

  const scrollFocused = () => {
    const el = document.activeElement;
    if (!isEditable(el)) return;
    // Чуть подождём, пока WebApp догонит viewportChanged и Telegram дорисует.
    requestAnimationFrame(() => {
      try {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      } catch {
        // pre-2020 webview без аргументов
        el.scrollIntoView();
      }
    });
  };

  document.addEventListener(
    "focusin",
    (e) => {
      if (!isEditable(e.target)) return;
      // Сразу скроллим, плюс ещё раз через 300 мс — клавиатура обычно
      // полностью выезжает к этому моменту и финальный размер viewport уже виден.
      scrollFocused();
      window.setTimeout(scrollFocused, 300);
    },
    { passive: true },
  );

  try {
    WebApp.onEvent("viewportChanged", () => scrollFocused());
  } catch {
    // не критично — focusin-обработчик уже справится
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

/**
 * Показать нативный Telegram-алерт. Возвращает Promise, который резолвится
 * после нажатия OK. Вне Telegram — fallback на window.alert.
 */
export function showAlert(message: string): Promise<void> {
  return new Promise((resolve) => {
    try {
      WebApp.showAlert(message, () => resolve());
    } catch {
      try {
        window.alert(message);
      } catch {
        // no-op
      }
      resolve();
    }
  });
}

export { WebApp };
