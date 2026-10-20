// @vitest-environment node
/**
 * VISUAL_AUDIT P1.6: два радиуса на весь интерфейс — `rounded-card` (12px) и
 * `rounded-tile` (8px), плюс `rounded-full` для пилюль.
 *
 * До прохода в разметке жили четыре ступени сразу: `md` (6px) и `lg` (8px)
 * обозначали одну и ту же роль (поля, кнопки, вложенные панели), `xl` (12px)
 * был карточкой, а `2xl` (16px) — редким исключением. Отсюда и ощущение
 * «радиусы по настроению», из-за которого карточка в карточке выглядела
 * случайной.
 *
 * Тест запрещает старые классы и произвольные `rounded-[..]`, чтобы шкала не
 * расползлась снова, и проверяет, что оба токена реально объявлены в
 * `tailwind.config.ts` — иначе класс молча не сгенерируется.
 */
import { describe, expect, it } from "vitest";
import tailwindConfig from "../tailwind.config.ts?raw";

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** Старые ступени Tailwind и любые произвольные радиусы. */
const LEGACY_RADIUS = /\brounded(?:-[a-z]+)*-(?:sm|md|lg|xl|2xl|3xl)\b|\brounded-\[/;
/** Одиночный `rounded` (4px) — тоже вне шкалы. */
const BARE_ROUNDED = /(?<![-\w])rounded(?![-\w])/;

describe("шкала радиусов", () => {
  it("видит исходники (иначе проверка ниже пустая)", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
  });

  it("не использует старые и произвольные радиусы", () => {
    const offenders: string[] = [];
    for (const [file, source] of Object.entries(sources)) {
      if (/\.test\./.test(file)) continue;
      source.split("\n").forEach((line, i) => {
        const legacy = line.match(LEGACY_RADIUS);
        const bare = line.match(BARE_ROUNDED);
        const hit = legacy ?? bare;
        if (hit) offenders.push(`${file}:${i + 1} — ${hit[0]}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it("объявляет card=12px и tile=8px в tailwind.config.ts", () => {
    expect(tailwindConfig).toMatch(/card:\s*"12px"/);
    expect(tailwindConfig).toMatch(/tile:\s*"8px"/);
  });
});
