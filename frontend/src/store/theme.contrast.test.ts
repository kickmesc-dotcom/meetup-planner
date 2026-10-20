/**
 * VISUAL_AUDIT P0.1: контраст основной кнопки.
 *
 * Аудит замерил 3.72:1 у белого текста на `#5288c1` (тёмная тема) — ниже нормы
 * WCAG AA 4.5:1 для мелкого текста. Палитру затемнили, и этот тест не даёт
 * вернуть «красивый, но нечитаемый» оттенок: считаем контраст по формуле WCAG,
 * а не сравниваем hex глазами.
 *
 * Заодно проверяем `hint` в обеих темах: подписи 10–12px должны читаться.
 */
import { describe, expect, it } from "vitest";
import { THEME_PALETTE, type Theme } from "./theme";

/** Относительная яркость по WCAG 2.x (sRGB). */
function luminance(hex: string): number {
  const raw = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(raw.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const THEMES: Theme[] = ["light", "dark"];

describe("палитра темы проходит WCAG AA", () => {
  it.each(THEMES)("текст основной кнопки читается (%s)", (theme) => {
    const p = THEME_PALETTE[theme];
    const ratio = contrast(
      p["--tg-theme-button-text-color"],
      p["--tg-theme-button-color"],
    );
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  });

  it.each(THEMES)("подсказки читаются на фоне (%s)", (theme) => {
    const p = THEME_PALETTE[theme];
    const ratio = contrast(
      p["--tg-theme-hint-color"],
      p["--tg-theme-bg-color"],
    );
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  });

  it.each(THEMES)("основной текст читается на фоне (%s)", (theme) => {
    const p = THEME_PALETTE[theme];
    const ratio = contrast(p["--tg-theme-text-color"], p["--tg-theme-bg-color"]);
    expect(ratio).toBeGreaterThanOrEqual(7);
  });
});
