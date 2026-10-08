// @vitest-environment jsdom
/**
 * GHG11(11): глобальная тема светлая/тёмная (по умолчанию тёмная).
 *
 * Проверяем обещания:
 *  - тема ставится ИНЛАЙН и с приоритетом `important` — иначе Telegram
 *    (у которого те же переменные инлайном, но без приоритета) перекрыл бы нас;
 *  - по умолчанию тёмная, выбор переживает перезапуск (localStorage);
 *  - свитчер меняет тему на противоположную.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_THEME,
  THEME_PALETTE,
  THEME_STORAGE_KEY,
  applyTheme,
  initTheme,
  readStoredTheme,
  useTheme,
} from "./theme";

const root = document.documentElement;

beforeEach(() => {
  localStorage.clear();
  root.removeAttribute("data-theme");
  root.removeAttribute("style");
  useTheme.setState({ theme: DEFAULT_THEME });
});

afterEach(() => {
  root.removeAttribute("data-theme");
  root.removeAttribute("style");
});

describe("applyTheme", () => {
  it("ставит переменные темы инлайном с приоритетом important", () => {
    applyTheme("dark");
    expect(root.style.getPropertyValue("--tg-theme-bg-color")).toBe(
      THEME_PALETTE.dark["--tg-theme-bg-color"],
    );
    // Приоритет важнее значения: обычным инлайном нас бы перекрыл Telegram.
    expect(root.style.getPropertyPriority("--tg-theme-bg-color")).toBe("important");
    expect(root.style.getPropertyPriority("--tg-theme-text-color")).toBe("important");
    expect(root.dataset.theme).toBe("dark");
  });

  it("для светлой темы значения другие (переключение не no-op)", () => {
    applyTheme("light");
    expect(root.style.getPropertyValue("--tg-theme-bg-color")).toBe(
      THEME_PALETTE.light["--tg-theme-bg-color"],
    );
    expect(root.style.getPropertyValue("--tg-theme-bg-color")).not.toBe(
      THEME_PALETTE.dark["--tg-theme-bg-color"],
    );
  });

  it("задаёт color-scheme: от него зависят нативные пикеры и скроллбары", () => {
    applyTheme("light");
    expect(root.style.colorScheme).toBe("light");
    expect(root.style.getPropertyPriority("--tg-color-scheme")).toBe("important");
  });
});

describe("useTheme", () => {
  it("по умолчанию тёмная", () => {
    expect(useTheme.getState().theme).toBe("dark");
  });

  it("переключатель меняет тему и запоминает выбор", () => {
    useTheme.getState().toggleTheme();
    expect(useTheme.getState().theme).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(root.dataset.theme).toBe("light");

    useTheme.getState().toggleTheme();
    expect(useTheme.getState().theme).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });
});

describe("initTheme", () => {
  it("без сохранённого выбора включает тёмную", () => {
    expect(readStoredTheme()).toBeNull();
    expect(initTheme()).toBe("dark");
    expect(useTheme.getState().theme).toBe("dark");
    expect(root.dataset.theme).toBe("dark");
  });

  it("уважает сохранённый светлый выбор", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    expect(initTheme()).toBe("light");
    expect(useTheme.getState().theme).toBe("light");
    expect(root.style.getPropertyValue("--tg-theme-bg-color")).toBe(
      THEME_PALETTE.light["--tg-theme-bg-color"],
    );
  });

  it("мусор в хранилище трактуется как «не выбрано»", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "rainbow");
    expect(readStoredTheme()).toBeNull();
    expect(initTheme()).toBe("dark");
  });
});
