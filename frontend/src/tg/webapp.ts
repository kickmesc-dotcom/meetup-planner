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
 * сфокусированный input уезжает из видимой области.
 *
 * GHG6 D3 (2026-05-20): первая итерация — `el.scrollIntoView({block:'center'})`.
 * Работало везде, кроме `ProxyScreen` (см. чеклист E2.1). Причина: `SubScreen`
 * оборачивает контент в собственный `overflow-y-auto`-контейнер, и в iOS-WKWebView
 * внутри Telegram дефолтный `scrollIntoView` иногда молча проваливается на
 * вложенный прокрутный родитель — особенно когда Telegram сам двигает
 * viewport под клавиатуру в тот же кадр.
 *
 * GHG6 E2 (2026-05-21): идём вверх от target'а, находим ближайший
 * `overflow-y: auto/scroll` родитель и явно скроллим его так, чтобы input
 * оказался в центре его видимой высоты. Параллельно вызываем стандартный
 * `scrollIntoView` — он закрывает случаи, когда прокручивать надо именно
 * window (нет вложенного скролл-контейнера). Без `data-scroll-root`-меток —
 * фикс автоматически распространяется на все будущие экраны с SubScreen-like
 * скролл-контейнером.
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

  const findScrollParent = (el: HTMLElement): HTMLElement | null => {
    // Идём по предкам, пока не найдём вертикальный скролл. Документ не считаем
    // (для него отдельная ветка — scrollIntoView в window).
    let p: HTMLElement | null = el.parentElement;
    while (p && p !== document.body) {
      const cs = getComputedStyle(p);
      const oy = cs.overflowY;
      if ((oy === "auto" || oy === "scroll") && p.scrollHeight > p.clientHeight) {
        return p;
      }
      p = p.parentElement;
    }
    return null;
  };

  const scrollFocused = () => {
    const el = document.activeElement;
    if (!isEditable(el)) return;
    // Чуть подождём, пока WebApp догонит viewportChanged и Telegram дорисует.
    requestAnimationFrame(() => {
      try {
        const parent = findScrollParent(el);
        if (parent) {
          // Считаем offsetTop относительно прокрутного родителя.
          const elRect = el.getBoundingClientRect();
          const parentRect = parent.getBoundingClientRect();
          const offsetWithinParent =
            elRect.top - parentRect.top + parent.scrollTop;
          const targetTop = Math.max(
            0,
            offsetWithinParent - parent.clientHeight / 2 + elRect.height / 2,
          );
          parent.scrollTo({ top: targetTop, behavior: "smooth" });
        }
        // Параллельно — стандартный scrollIntoView (на случай, когда родителя
        // нет и скроллить надо window).
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      } catch {
        // pre-2020 webview без аргументов
        try { el.scrollIntoView(); } catch { /* noop */ }
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
      // E2.2: если viewport совсем узкий (iPhone в landscape, мини-режим
      // WebApp), просим Telegram развернуться. Без вреда: уже-expanded — no-op.
      try {
        if ((WebApp.viewportStableHeight ?? 0) < 500) WebApp.expand();
      } catch {
        // в окружении без WebApp — игнорируем
      }
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

/**
 * Telegram WebApp confirm-диалог с двумя кнопками. Возвращает true,
 * если пользователь нажал «OK». Вне Telegram — fallback на
 * `window.confirm`.
 */
export function showConfirm(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    try {
      WebApp.showConfirm(message, (ok: boolean) => resolve(Boolean(ok)));
    } catch {
      try {
        resolve(window.confirm(message));
      } catch {
        resolve(false);
      }
    }
  });
}

export { WebApp };
