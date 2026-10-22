// @vitest-environment jsdom
/**
 * Вход в веб-версию по ссылке: `?access=` → localStorage → заголовок.
 *
 * Три правила, которые легко сломать незаметно:
 *  1. токен убирается из адресной строки (иначе останется в истории/логах);
 *  2. внутри Telegram главнее `initData`, а не локальный токен браузера;
 *  3. после 401 токен забывается, чтобы приложение показало «нужен вход».
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/tg/webapp", () => ({ getInitData: vi.fn(() => "") }));

import { getInitData } from "@/tg/webapp";
import {
  api,
  captureAccessTokenFromUrl,
  clearAccessToken,
  getAccessToken,
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
  clearAccessToken();
  mockedInitData.mockReturnValue("");
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearAccessToken();
});

describe("captureAccessTokenFromUrl", () => {
  it("забирает токен и вычищает его из адреса", () => {
    window.history.replaceState(null, "", "/?access=sweb_secret&startapp=feed");
    expect(captureAccessTokenFromUrl()).toBe(true);
    expect(getAccessToken()).toBe("sweb_secret");
    expect(window.location.search).toBe("?startapp=feed");
  });

  it("без параметра ничего не делает", () => {
    window.history.replaceState(null, "", "/?startapp=feed");
    expect(captureAccessTokenFromUrl()).toBe(false);
    expect(getAccessToken()).toBeNull();
    expect(window.location.search).toBe("?startapp=feed");
  });
});

describe("api", () => {
  it("без initData отправляет X-Access-Token", async () => {
    window.history.replaceState(null, "", "/?access=sweb_secret");
    captureAccessTokenFromUrl();
    const fetchFn = stubFetch();

    await api("/api/me");

    const headers = sentHeaders(fetchFn);
    expect(headers.get("X-Access-Token")).toBe("sweb_secret");
    expect(headers.get("Authorization")).toBeNull();
  });

  it("внутри Telegram отправляет initData и не подставляет токен", async () => {
    window.history.replaceState(null, "", "/?access=sweb_secret");
    captureAccessTokenFromUrl();
    mockedInitData.mockReturnValue("query_id=1&hash=abc");
    const fetchFn = stubFetch();

    await api("/api/me");

    const headers = sentHeaders(fetchFn);
    expect(headers.get("Authorization")).toBe("tma query_id=1&hash=abc");
    expect(headers.get("X-Access-Token")).toBeNull();
  });

  it("на 401 забывает токен", async () => {
    window.history.replaceState(null, "", "/?access=sweb_secret");
    captureAccessTokenFromUrl();
    stubFetch(401);

    await expect(api("/api/me")).rejects.toBeTruthy();
    expect(getAccessToken()).toBeNull();
  });
});
