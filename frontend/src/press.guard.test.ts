/**
 * Страж отклика нажатия (план, раздел 10).
 *
 * Зачем тест. «Кнопка должна отзываться» — не то правило, которое держится
 * само: в приложении 335 кнопок, и до этого прохода у большинства отклика не
 * было вовсе, а у остальных он был разным (0.9 / 0.95 / 0.98 / 0.99) и
 * написанным в разметке через `active:scale-*`. Такой класс:
 *
 *  • обходит `prefers-reduced-motion` — человек с вестибулярной чувствительностью
 *    получает движение, которое просил отключить;
 *  • не знает про `:disabled` — кнопка сжимается, хотя действие не произойдёт;
 *  • расходится по значениям от экрана к экрану.
 *
 * Поэтому отклик живёт в одном месте — `styles.css` (правило на `button` и
 * `[role="button"]`, а не класс в разметке). CSS через `?raw` в Vitest читается
 * пустым (CSS подменяется заглушкой), поэтому сам стиль проверяется на сборке
 * (`grep` по `dist/assets/*.css`, см. DEPLOY_NOTES), а здесь — разметка:
 * ни одного ручного `active:scale` и подключённый файл стилей.
 */
import { describe, expect, it } from "vitest";
import mainSource from "./main.tsx?raw";

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("отклик нажатия", () => {
  it("видит исходники (иначе проверка ниже пустая)", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
  });

  it("в разметке нет ручных active:scale — они обходят reduced-motion", () => {
    const offenders: string[] = [];
    for (const [path, raw] of Object.entries(sources)) {
      if (path.includes(".test.")) continue;
      const relative = path.replace(/^\.\//, "");
      if (relative.startsWith("_legacy/")) continue;
      raw.split("\n").forEach((line, index) => {
        if (line.includes("active:scale")) offenders.push(`${relative}:${index + 1}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it("файл стилей подключён — иначе правило просто не доедет до экрана", () => {
    expect(mainSource).toContain('import "./styles.css"');
  });
});
