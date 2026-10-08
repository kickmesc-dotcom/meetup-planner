/**
 * Глобальная тема приложения: светлая / тёмная, по умолчанию ТЁМНАЯ.
 *
 * Почему не полагаемся на тему Telegram. Мини-апп открывается внутри клиента, и
 * Telegram сам подставляет `--tg-theme-*` — но у этой подстановки два изъяна:
 * у одного и того же человека тема зависит от клиента и устройства (лента
 * «прыгает» цветами между телефоном и десктопом), а светлый вариант Telegram
 * даёт подсказку `#999` с контрастом 2.5:1 — вторичный текст перестаёт читаться.
 *
 * Как перекрываем. Telegram ставит переменные как ИНЛАЙН-стиль на `<html>` БЕЗ
 * `important` (см. `setCssProperty` в telegram-web-app.js: `root.style.setProperty`).
 * Поэтому и мы пишем туда же инлайн, но с приоритетом `important`: инлайн
 * `important` бьёт инлайн обычный, и перекрытие держится даже когда Telegram
 * перерисует свои значения на `themeChanged`. Стилей в CSS для этого не хватило
 * бы — они проигрывают инлайну.
 *
 * Что это значит для остального кода: переменные `--tg-theme-*` остаются ЕДИНЫМ
 * источником правды (`tailwind.config.ts` маппит их в `bg-tg-*`/`text-tg-*`),
 * меняется только тот, кто их задаёт. Ни один компонент про тему не знает.
 */
import { create } from "zustand";

export type Theme = "dark" | "light";

/** Ключ в localStorage: выбранная участником тема. */
export const THEME_STORAGE_KEY = "ghg.theme.v1";

export const DEFAULT_THEME: Theme = "dark";

/**
 * Палитры. Значения — официальные цвета Telegram (`themeParams`) для тёмной
 * «ночной» и светлой схем, кроме `hint-color`: там сознательно взят более
 * контрастный `#707579` вместо `#999999`, иначе подписи не читаются (AA).
 */
export const THEME_PALETTE: Record<Theme, Record<string, string>> = {
  dark: {
    "--tg-theme-bg-color": "#17212b",
    "--tg-theme-secondary-bg-color": "#232e3c",
    "--tg-theme-text-color": "#f5f5f5",
    "--tg-theme-hint-color": "#7d8b99",
    "--tg-theme-link-color": "#6ab3f3",
    "--tg-theme-button-color": "#5288c1",
    "--tg-theme-button-text-color": "#ffffff",
    "--tg-theme-header-bg-color": "#17212b",
    "--tg-theme-section-bg-color": "#17212b",
    "--tg-theme-section-header-text-color": "#7d8b99",
    "--tg-theme-subtitle-text-color": "#7d8b99",
    "--tg-theme-accent-text-color": "#6ab3f3",
    "--tg-theme-destructive-text-color": "#ec3942",
  },
  light: {
    "--tg-theme-bg-color": "#ffffff",
    "--tg-theme-secondary-bg-color": "#f1f1f1",
    "--tg-theme-text-color": "#000000",
    "--tg-theme-hint-color": "#707579",
    "--tg-theme-link-color": "#2481cc",
    "--tg-theme-button-color": "#2481cc",
    "--tg-theme-button-text-color": "#ffffff",
    "--tg-theme-header-bg-color": "#ffffff",
    "--tg-theme-section-bg-color": "#ffffff",
    "--tg-theme-section-header-text-color": "#707579",
    "--tg-theme-subtitle-text-color": "#707579",
    "--tg-theme-accent-text-color": "#2481cc",
    "--tg-theme-destructive-text-color": "#e53935",
  },
};

/** Прочитанная тема из localStorage или `null`. Никогда не бросает. */
export function readStoredTheme(): Theme | null {
  try {
    if (typeof localStorage === "undefined") return null;
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    return raw === "dark" || raw === "light" ? raw : null;
  } catch {
    return null;
  }
}

function storeTheme(theme: Theme): void {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // приватный режим / переполнение — тема просто не переживёт перезапуск
  }
}

/**
 * Нанести тему на документ: инлайн-переменные с `important` + `color-scheme`
 * (от него зависят нативные пикеры и скроллбары). Чистая по отношению к React —
 * вызывается и до первого рендера, и по тапу свитчера.
 */
export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  if (!root?.style?.setProperty) return;
  for (const [name, value] of Object.entries(THEME_PALETTE[theme])) {
    root.style.setProperty(name, value, "important");
  }
  root.style.setProperty("--tg-color-scheme", theme, "important");
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

export const useTheme = create<ThemeState>((set, get) => ({
  theme: DEFAULT_THEME,
  setTheme: (theme) => {
    applyTheme(theme);
    storeTheme(theme);
    set({ theme });
  },
  toggleTheme: () => get().setTheme(get().theme === "dark" ? "light" : "dark"),
}));

/**
 * Стартовая тема приложения: сохранённый выбор, иначе тёмная по умолчанию.
 * Зовётся один раз в `main.tsx` — до рендера, чтобы не было вспышки чужой темы.
 */
export function initTheme(): Theme {
  const theme = readStoredTheme() ?? DEFAULT_THEME;
  applyTheme(theme);
  useTheme.setState({ theme });
  return theme;
}
