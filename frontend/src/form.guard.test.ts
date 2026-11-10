/**
 * Страж форм этапа 3 (`docs/AAA_ROADMAP.md`).
 *
 * Правило простое: форма собирается через `FormField`, а не руками. Иначе
 * снова появится поле с подписью-`span`, без `aria-describedby` и с ошибкой,
 * которую скринридер читает как посторонний текст. Проверка статическая —
 * файл, который содержит `<form`, обязан импортировать `FormField` — и
 * намеренно консервативна: она не диктует разметку, только вход.
 *
 * Вторая проверка держит сам `FormField`: если из него уберут связь описания
 * или объявление ошибки, все формы разом потеряют то, ради чего он есть.
 */
import { describe, expect, it } from "vitest";
import fieldSource from "./components/FormField?raw";

const sources = import.meta.glob("./**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("формы собираются через FormField", () => {
  it("видит исходники (иначе проверки ниже пустые)", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    expect(fieldSource).toContain("aria-describedby");
  });

  it("нет формы без FormField", () => {
    const offenders: string[] = [];
    for (const [path, raw] of Object.entries(sources)) {
      if (path.includes(".test.") || path.includes("_legacy/")) continue;
      if (!raw.includes("<form")) continue;
      if (!raw.includes('from "@/components/FormField"')) {
        offenders.push(path.replace(/^\.\//, ""));
      }
    }
    expect(offenders).toEqual([]);
  });

  it("FormField связывает подсказку и ошибку и объявляет ошибку", () => {
    expect(fieldSource).toContain("const described = [describedBy, hintId, ownErrorId]");
    expect(fieldSource).toContain('role="alert"');
    expect(fieldSource).toContain('"aria-invalid"');
    expect(fieldSource).toContain('"aria-required"');
  });
});
