/**
 * Пути благодарностей — `/api/kudos/*`, а не `/api/hr/kudos/*`.
 *
 * Регрессия 31.10.2026: на проде все три запроса отвечали 404, и карточка в
 * ленте честно писала «Благодарности сейчас не загрузились — остальное в ленте
 * работает». Причина: сервер подключает `routes_hr` с префиксом `/api`, а ручка
 * внутри объявлена как `/kudos/week`; фронт же стучался в `/api/hr/...`.
 *
 * Тест держит именно путь: он не дублирует серверную логику, а фиксирует
 * контракт, который уже один раз разъехался.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const calls: string[] = [];

vi.mock("./client", () => ({
  api: vi.fn(async (path: string) => {
    calls.push(path);
    return {} as never;
  }),
}));

import { fetchKudosPeople, fetchKudosWeek, giveKudos } from "./kudos";

beforeEach(() => {
  calls.length = 0;
});

describe("пути API благодарностей", () => {
  it("недельная сводка — /api/kudos/week", async () => {
    await fetchKudosWeek();
    expect(calls).toEqual(["/api/kudos/week"]);
  });

  it("список коллег — /api/kudos/people", async () => {
    await fetchKudosPeople();
    expect(calls).toEqual(["/api/kudos/people"]);
  });

  it("отправка — POST /api/kudos", async () => {
    await giveKudos(7, "спасибо");
    expect(calls).toEqual(["/api/kudos"]);
  });
});
