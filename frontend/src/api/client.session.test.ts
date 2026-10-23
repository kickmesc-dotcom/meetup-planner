// @vitest-environment jsdom
/**
 * Сессия по почте: `Authorization: Bearer` и порядок старшинства токенов.
 *
 * Пароль на клиенте не живёт — только токен сессии, потому что его сервер
 * может отозвать. Проверяем три вещи, которые легко сломать незаметно:
 *  1. сохранённая сессия уходит `Bearer`-заголовком;
 *  2. внутри Telegram главнее `initData`, иначе мини-апп открылся бы чужим
 *     человеком с забытого ноутбука;
 *  3. на 401 токен забывается — приложение покажет форму входа, а не будет
 *     долбить сервер мёртвым заголовком.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/tg/webapp", () => ({ getInitData: vi.fn(() => "") }));

import { getInitData } from "@/tg/webapp";
import {
  api,
  clearAllTokens,
  clearSessionToken,
  getAccessToken,
  getSessionToken,
  setAccessToken,
  setSessionToken,
} from "./client";

const mockedInitData = vi.mocked(getInitData);

function stubFetch(status = 200) {
  const fn = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ ok: true }), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

function sentHeaders(fn: ReturnType<typeof stubFetch>): Headers {
  const init = fn.mock.calls[0][1] as RequestInit;
  return init.headers as Headers;
}

beforeEach(() => {
  clearAllTokens();
  mockedInitData.mockReturnValue("");
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearAllTokens();
});

describe("хранение сессии", () => {
  it("setSessionToken обрезает пробелы и читается обратно", () => {
    setSessionToken("  sess_abc  ");
    expect(getSessionToken()).toBe("sess_abc");
  });

  it("clearAllTokens забывает и сессию, и ссылку доступа", () => {
    setSessionToken("sess_abc");
    setAccessToken("sweb_abc");
    clearAllTokens();
    expect(getSessionToken()).toBeNull();
    expect(getAccessToken()).toBeNull();
  });
});

describe("порядок старшинства токенов", () => {
  it("сессия по почте уходит Bearer-заголовком", async () => {
    setSessionToken("sess_abc");
    const fetchFn = stubFetch();

    await api("/api/me");

    const headers = sentHeaders(fetchFn);
    expect(headers.get("Authorization")).toBe("Bearer sess_abc");
    expect(headers.get("X-Access-Token")).toBeNull();
  });

  it("сессия главнее ссылки доступа из бота", async () => {
    setSessionToken("sess_abc");
    setAccessToken("sweb_abc");
    const fetchFn = stubFetch();

    await api("/api/me");

    const headers = sentHeaders(fetchFn);
    expect(headers.get("Authorization")).toBe("Bearer sess_abc");
    expect(headers.get("X-Access-Token")).toBeNull();
  });

  it("внутри Telegram главнее initData", async () => {
    setSessionToken("sess_abc");
    mockedInitData.mockReturnValue("query_id=1&hash=abc");
    const fetchFn = stubFetch();

    await api("/api/me");

    const headers = sentHeaders(fetchFn);
    expect(headers.get("Authorization")).toBe("tma query_id=1&hash=abc");
    expect(headers.get("X-Access-Token")).toBeNull();
  });

  it("на 401 забывает просроченную сессию", async () => {
    setSessionToken("sess_abc");
    stubFetch(401);

    await expect(api("/api/me")).rejects.toBeTruthy();
    expect(getSessionToken()).toBeNull();
  });

  it("на 401 внутри Telegram локальную сессию не трогает", async () => {
    setSessionToken("sess_abc");
    mockedInitData.mockReturnValue("query_id=1&hash=abc");
    stubFetch(401);

    await expect(api("/api/me")).rejects.toBeTruthy();
    expect(getSessionToken()).toBe("sess_abc");
  });

  it("clearSessionToken не задевает ссылку доступа", () => {
    setSessionToken("sess_abc");
    setAccessToken("sweb_abc");
    clearSessionToken();
    expect(getSessionToken()).toBeNull();
    expect(getAccessToken()).toBe("sweb_abc");
  });
});
