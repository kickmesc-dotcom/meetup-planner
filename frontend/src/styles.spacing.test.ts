// @vitest-environment node
/**
 * UI_UX_PRO_MAX §7 `spacing-scale`: отступы — шкала с шагом 4px.
 *
 * До прохода padding и gap задавались полушагом 2px (`p-0.5`, `gap-0.5`):
 * на глаз это читалось как «случайно слиплось», а на разных экранах давало
 * разную плотность. Здесь два обещания:
 *
 *  - в padding/gap/margin нет `*-0.5` (2px);
 *  - нет произвольных `p-[13px]` и подобных.
 *
 * `mt-0.5`/`top-0.5`/`right-0.5` — не отступ раскладки, а оптический сдвиг
 * строки или значка относительно соседнего текста; они остаются осознанно.
 */
import { describe, expect, it } from "vitest";

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const LAYOUT_HALF =
  /\b(?:p|px|py|pt|pb|pl|pr|gap|gap-x|gap-y|space-x|space-y|m|mx|my)-0\.5\b/;
const ARBITRARY_SPACING =
  /\b(?:p|px|py|pt|pb|pl|pr|gap|gap-x|gap-y|space-x|space-y|m|mx|my|mt|mb|ml|mr)-\[\d+px\]/;

describe("шкала отступов", () => {
  it("действительно видит исходники", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
  });

  it("не использует полушаг 2px в padding/gap/margin", () => {
    const offenders: string[] = [];
    for (const [file, source] of Object.entries(sources)) {
      if (/\.test\./.test(file) || file.includes("_legacy/")) continue;
      source.split("\n").forEach((line, i) => {
        const match = line.match(LAYOUT_HALF);
        if (match) offenders.push(`${file}:${i + 1} — ${match[0]}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it("не использует произвольные px-отступы", () => {
    const offenders: string[] = [];
    for (const [file, source] of Object.entries(sources)) {
      if (/\.test\./.test(file) || file.includes("_legacy/")) continue;
      source.split("\n").forEach((line, i) => {
        const match = line.match(ARBITRARY_SPACING);
        if (match) offenders.push(`${file}:${i + 1} — ${match[0]}`);
      });
    }
    expect(offenders).toEqual([]);
  });
});
