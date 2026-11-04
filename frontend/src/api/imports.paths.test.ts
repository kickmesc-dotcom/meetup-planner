/**
 * Пути импорта — `/api/import/*`, а не `/api/hr/import/*`.
 *
 * Регрессия 31.10 и 04.11 была одной и той же: `routes_hr` монтируется под
 * `/api`, фронт звал `/api/hr/...`. Для импорта это особенно дорого: экран
 * показывал бы «файл не разобрался» на исправном файле.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const calls: string[] = [];

vi.mock("./client", () => ({
  api: vi.fn(async (path: string) => {
    calls.push(path);
    return {} as never;
  }),
}));

import { applyImport, previewImport } from "./imports";

beforeEach(() => {
  calls.length = 0;
});

describe("пути API импорта", () => {
  it("предпросмотр — POST /api/import/preview", async () => {
    await previewImport({ text: "имя\nАнна" });
    expect(calls).toEqual(["/api/import/preview"]);
  });

  it("применение — POST /api/import/apply", async () => {
    await applyImport({ text: "имя\nАнна", kind: "people" });
    expect(calls).toEqual(["/api/import/apply"]);
  });
});
