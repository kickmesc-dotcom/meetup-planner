// @vitest-environment jsdom
/**
 * Режим проверки (MEGAPROMT3, п. 21–28).
 *
 * Проверяем обещания клиента:
 *  - сеанс переживает перезапуск мини-аппа (localStorage);
 *  - мусор в хранилище не включает режим и не ломает приложение;
 *  - мёртвый сеанс (сервер перезапустили) не вешает запросы в 409: заголовок
 *    забывается, запрос повторяется от настоящего пользователя.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/tg/webapp", () => ({ getInitData: () => "init-data" }));

import { api } from "@/api/client";
import {
  SIMULATION_STORAGE_KEY,
  useSimulation,
} from "./simulation";

function stored(state: Record<string, unknown>): void {
  localStorage.setItem(SIMULATION_STORAGE_KEY, JSON.stringify(state));
}

beforeEach(() => {
  localStorage.clear();
  useSimulation.getState().clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useSimulation", () => {
  it("стартует сеанс и переживает перезапуск", async () => {
    useSimulation.getState().start({
      sessionId: 7,
      subjectName: "Проверяемый",
      departmentName: "Цех",
      mode: "new",
    });
    expect(useSimulation.getState().sessionId).toBe(7);
    expect(JSON.parse(localStorage.getItem(SIMULATION_STORAGE_KEY)!)).toMatchObject({
      sessionId: 7,
      subjectName: "Проверяемый",
    });

    vi.resetModules();
    const fresh = await import("./simulation");
    expect(fresh.useSimulation.getState().sessionId).toBe(7);
    expect(fresh.useSimulation.getState().departmentName).toBe("Цех");
  });

  it("выход стирает и состояние, и хранилище", () => {
    useSimulation.getState().start({
      sessionId: 3,
      subjectName: "Кто-то",
      departmentName: null,
      mode: "as_is",
    });
    useSimulation.getState().clear();
    expect(useSimulation.getState().sessionId).toBeNull();
    expect(localStorage.getItem(SIMULATION_STORAGE_KEY)).toBeNull();
  });

  it("мусор в хранилище не включает режим", async () => {
    stored({ sessionId: "нет", mode: "hack" });
    vi.resetModules();
    const fresh = await import("./simulation");
    expect(fresh.useSimulation.getState().sessionId).toBeNull();
    expect(fresh.useSimulation.getState().mode).toBeNull();
  });
});

describe("api в режиме проверки", () => {
  it("добавляет заголовок сеанса", async () => {
    useSimulation.getState().start({
      sessionId: 42,
      subjectName: "Проверяемый",
      departmentName: null,
      mode: "new",
    });
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response("{}", { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api("/api/me/employee");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Simulation-Session")).toBe("42");
  });

  it("мёртвый сеанс забывается и запрос повторяется без заголовка", async () => {
    useSimulation.getState().start({
      sessionId: 42,
      subjectName: "Проверяемый",
      departmentName: null,
      mode: "new",
    });
    const fetchMock = vi
      .fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response("{}", { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "simulation_inactive" }), {
          status: 409,
        }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api<{ id: number }>("/api/me/employee")).resolves.toEqual({ id: 1 });
    expect(useSimulation.getState().sessionId).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const retry = fetchMock.mock.calls[1][1] as RequestInit;
    expect(new Headers(retry.headers).has("X-Simulation-Session")).toBe(false);
  });

  it("другие 409 не глотает", async () => {
    useSimulation.getState().start({
      sessionId: 42,
      subjectName: "Проверяемый",
      departmentName: null,
      mode: "new",
    });
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify({ detail: "task_already_closed" }), { status: 409 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api("/api/tasks/1/done", { method: "POST" })).rejects.toMatchObject({
      status: 409,
      detail: "task_already_closed",
    });
    expect(useSimulation.getState().sessionId).toBe(42);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
