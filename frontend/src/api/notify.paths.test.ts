// @vitest-environment jsdom
/**
 * Пути личных подписок — `/api/notify-prefs`, а не `/api/hr/notify-prefs`.
 *
 * Регрессия 04.11.2026 (та же, что была у благодарностей 31.10): сервер
 * подключает `routes_hr` с префиксом `/api`, ручка внутри объявлена как
 * `/notify-prefs`, а фронт стучался в `/api/hr/...` и получал 404 — тумблер
 * сводки на проде не работал бы. Тест держит контракт, который уже один раз
 * разъехался.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const calls: string[] = [];

vi.mock("./client", () => ({
  api: vi.fn(async (path: string) => {
    calls.push(path);
    return {} as never;
  }),
}));

import { fetchNotifyPrefs, setNotifyPref } from "./hr";

beforeEach(() => {
  calls.length = 0;
});

describe("пути API личных подписок", () => {
  it("чтение — GET /api/notify-prefs", async () => {
    await fetchNotifyPrefs();
    expect(calls).toEqual(["/api/notify-prefs"]);
  });

  it("правка — PATCH /api/notify-prefs", async () => {
    await setNotifyPref("digest", true);
    expect(calls).toEqual(["/api/notify-prefs"]);
  });
});
