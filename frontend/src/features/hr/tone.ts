/**
 * Цвета людей и подразделений для ленты и карточек.
 *
 * Зачем не палитра из темы. Цвет здесь — не смысл, а «ярлык на память»: по
 * нему в ленте видно, что пять строк подряд написал один человек, а не пятеро
 * разных. Поэтому важны два свойства:
 *
 * 1. **Стабильность.** Один и тот же человек всегда одного цвета — иначе
 *    ярлык не запоминается. Цвет считается из id, а не из порядка строк.
 * 2. **Совместимость с темой.** Оттенок задаётся как полупрозрачный слой
 *    (`hsl(... / 0.14)`) поверх текущего фона, поэтому читается и в светлой,
 *    и в тёмной теме. Текст остаётся `tg-text` — контраст не зависит от
 *    выбранного оттенка.
 */

export interface Tone {
  /** Оттенок 0–359 — пригодится для акцентов и границ. */
  hue: number;
  /** Граница пилюли — «аутлайн» вокруг имени. */
  border: string;
  /** Мягкая подложка той же природы. */
  soft: string;
}

// Восемь оттенков, разнесённых по кругу: соседние люди не сливаются.
const HUES = [212, 268, 330, 14, 42, 96, 164, 190];

// Подразделения сдвинуты по кругу относительно людей: «🍳 Повара» и «Дима»
// не должны внезапно оказаться одного цвета.
const DEPARTMENT_OFFSET = 23;

function hash(seed: number | string): number {
  if (typeof seed === "number") return Math.abs(Math.trunc(seed)) || 1;
  let value = 0;
  for (let i = 0; i < seed.length; i += 1) {
    value = (value * 31 + seed.charCodeAt(i)) % 100_000;
  }
  return value || 1;
}

function makeTone(hue: number): Tone {
  return {
    hue,
    border: `hsl(${hue} 58% 48% / 0.55)`,
    soft: `hsl(${hue} 62% 52% / 0.14)`,
  };
}

/** Цвет конкретного человека (стабилен по employee_id). */
export function personTone(seed: number | string | null | undefined): Tone {
  if (seed === null || seed === undefined) return makeTone(HUES[0]);
  const index = hash(seed) % HUES.length;
  return makeTone(HUES[index]);
}

/** Цвет подразделения — свой, не совпадающий с людьми «по умолчанию». */
export function departmentTone(departmentId: number | null | undefined): Tone {
  if (departmentId === null || departmentId === undefined) {
    return makeTone((HUES[0] + DEPARTMENT_OFFSET) % 360);
  }
  const index = hash(departmentId) % HUES.length;
  return makeTone((HUES[index] + DEPARTMENT_OFFSET) % 360);
}
