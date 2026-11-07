// @vitest-environment node
/**
 * UI_UX_PRO_MAX §4 `elevation-consistent`: три роли тени, а не четыре ступени
 * Tailwind по месту.
 *
 * До прохода в разметке жили `shadow-sm`, `shadow-lg`, `shadow-xl` и
 * `shadow-2xl` без правила: карточка в потоке и пилюля над контентом получали
 * одинаковую глубину, шит и попап — разную, а новая кнопка брала ту ступень,
 * которую подсказала память. Глубина перестала что-либо означать.
 *
 * Шкала в `tailwind.config.ts`:
 *   `raised` — приподнято над потоком (пилюли, кнопки);
 *   `floating` — плавает над контентом (тост, «Наверх», skip-link);
 *   `sheet` — поверхность поверх страницы (шиты, попапы).
 *
 * Тест ловит и старые ступени, и произвольные `shadow-[..]`: иначе шкала
 * расползётся снова, как это уже было с радиусами.
 */
import { describe, expect, it } from "vitest";
import tailwindConfig from "../tailwind.config.ts?raw";

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** Старые ступени Tailwind и любые произвольные тени. */
const LEGACY_SHADOW =
  /\bshadow-(?:sm|md|lg|xl|2xl|3xl|inner)\b|\bshadow-\[/;

describe("шкала теней", () => {
  it("видит исходники (иначе проверка ниже пустая)", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
  });

  it("не использует старые и произвольные ступени", () => {
    const offenders: string[] = [];
    for (const [file, source] of Object.entries(sources)) {
      if (/\.test\./.test(file) || file.includes("_legacy")) continue;
      source.split("\n").forEach((line, i) => {
        const hit = line.match(LEGACY_SHADOW);
        if (hit) offenders.push(`${file}:${i + 1} — ${hit[0]}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it("объявляет raised, floating и sheet в tailwind.config.ts", () => {
    for (const token of ["raised", "floating", "sheet"]) {
      expect(tailwindConfig).toMatch(new RegExp(`\\b${token}:`));
    }
  });
});
