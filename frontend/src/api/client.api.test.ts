// @vitest-environment jsdom
/**
 * Поведение `api()`: какие заголовки уходят, что происходит с 401, 204 и с
 * закончившимся сеансом проверки.
 *
 * Ошибки здесь стоят дорого: неверный заголовок означает чужую личность или
 * потерянный филиал, а незачищенный токен — бесконечные 401 вместо формы входа.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const simulation = { sessionId: null as number | null, clear: vi.fn() };

vi.mock("@/tg/webapp", () => ({ getInitData: vi.fn(() => "") }));
vi.mock("@/store/simulation", () => ({
  useSimulation: { getState: () => simulation },
}));

import { ApiError, api, setActiveOrg, setSessionToken } from "./client";

const fetchMock = vi.fn();

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => body,
  } as unknown as Response;
}

beforeEach(() => {
  localStorage.clear();
  simulation.sessionId = null;
  simulation.clear.mockReset();
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function lastInit(): RequestInit & { headers: Headers } {
  return fetchMock.mock.calls.at(-1)?.[1] as RequestInit & { headers: Headers };
}

describe("api(): заголовки", () => {
  it("ставит токен сессии в Authorization", async () => {
    setSessionToken("sess-1");
    await api("/api/me");
    expect(lastInit().headers.get("Authorization")).toBe("Bearer sess-1");
  });

  it("ставит JSON только при теле и не перезаписывает свой Content-Type", async () => {
    await api("/api/menu", { method: "POST", body: JSON.stringify({}) });
    expect(lastInit().headers.get("Content-Type")).toBe("application/json");

    await api("/api/menu", {
      method: "POST",
      body: "raw",
      headers: { "Content-Type": "text/plain" },
    });
    expect(lastInit().headers.get("Content-Type")).toBe("text/plain");
  });

  it("не ставит JSON для FormData: boundary выставляет браузер", async () => {
    await api("/api/upload", { method: "POST", body: new FormData() });
    expect(lastInit().headers.has("Content-Type")).toBe(false);
  });

  it("передаёт выбранный филиал и сеанс проверки", async () => {
    setActiveOrg(12);
    simulation.sessionId = 5;
    await api("/api/users");
    expect(lastInit().headers.get("X-Org-Id")).toBe("12");
    expect(lastInit().headers.get("X-Simulation-Session")).toBe("5");
  });
});

describe("api(): ответы", () => {
  it("возвращает undefined на 204", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => ({}),
    } as unknown as Response);
    await expect(api("/api/thing", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("превращает отказ в ApiError с кодом из detail", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "bad_email" }, 400));
    await expect(api("/api/auth/login")).rejects.toMatchObject({
      status: 400,
      detail: "bad_email",
    });
  });

  it("на 401 без initData забывает токены", async () => {
    setSessionToken("sess-1");
    fetchMock.mockResolvedValue(jsonResponse({ detail: "session_invalid" }, 401));
    await expect(api("/api/me")).rejects.toBeInstanceOf(ApiError);
    expect(localStorage.getItem("semitask.session_token")).toBeNull();
  });

  it("повторяет запрос без сеанса, если проверка закончилась", async () => {
    simulation.sessionId = 3;
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "simulation_inactive" }, 409))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    await expect(api("/api/users")).resolves.toEqual({ ok: true });
    expect(simulation.clear).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
