/**
 * Прокси `/api/*` на своём домене: контракт пересылки.
 *
 * Зачем тест на «просто переслать». У прозрачного прокси нет своей логики, но
 * есть класс ошибок, который виден только в проде и сразу у всех: заголовки
 * тела (`content-encoding`/`content-length`) от распакованного ответа ломают
 * загрузку, потерянный `Authorization` разлогинивает, а потерянный
 * `X-Forwarded-For` сажает всех посетителей в один счётчик лимита — и
 * приложение начинает отвечать `429` «просто так».
 */
import { describe, expect, it, vi, beforeEach } from "vitest";

import { onRequest } from "../../functions/api/[[path]]";

const ORIGIN = "https://backend.test";

function context(request: Request, env: Record<string, string> = {}) {
  return {
    request,
    env: { API_ORIGIN: ORIGIN, ...env },
    waitUntil: () => undefined,
  };
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

describe("прокси /api/*", () => {
  it("пересылает путь с параметрами и метод", async () => {
    fetchMock.mockResolvedValue(
      new Response("{}", { status: 200, headers: { "content-type": "application/json" } }),
    );

    await onRequest(
      context(new Request("https://app.test/api/tasks?include_closed=false&x=1")),
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(
      `${ORIGIN}/api/tasks?include_closed=false&x=1`,
    );
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("GET");
  });

  it("сохраняет личность и настоящий адрес посетителя", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));

    const request = new Request("https://app.test/api/me", {
      headers: {
        authorization: "tma init-data",
        "x-forwarded-for": "203.0.113.7",
        "x-simulation-session": "12",
        origin: "https://app.test",
        referer: "https://app.test/",
      },
    });

    await onRequest(context(request));

    const sent = (fetchMock.mock.calls[0][1] as RequestInit).headers as Headers;
    expect(sent.get("authorization")).toBe("tma init-data");
    // Без этого все посетители попали бы в один ключ лимита на адресе края.
    expect(sent.get("x-forwarded-for")).toBe("203.0.113.7");
    expect(sent.get("x-simulation-session")).toBe("12");
    // Наш origin апстриму не нужен: CORS проверяет браузер, а не прокси.
    expect(sent.get("origin")).toBeNull();
    expect(sent.get("referer")).toBeNull();
  });

  it("не отдаёт браузеру заголовки тела от распакованного ответа", async () => {
    fetchMock.mockResolvedValue(
      new Response('{"ok":true}', {
        status: 418,
        headers: {
          "content-type": "application/json",
          "content-encoding": "gzip",
          "content-length": "999",
          "access-control-allow-origin": "*",
          "x-request-id": "abc",
        },
      }),
    );

    const response = await onRequest(context(new Request("https://app.test/api/me")));

    expect(response.status).toBe(418);
    // Тело уже распаковано: с этими заголовками браузер получил бы битый JSON.
    expect(response.headers.get("content-encoding")).toBeNull();
    expect(response.headers.get("content-length")).toBeNull();
    expect(response.headers.get("access-control-allow-origin")).toBeNull();
    // Чужое кэшировать нельзя: ответ зависит от человека.
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("x-api-proxy")).toBe("pages");
    expect(response.headers.get("x-request-id")).toBe("abc");
    expect(await response.text()).toBe('{"ok":true}');
  });

  it("не отменяет публичный кэш, который бэкенд объявил сам", async () => {
    // Аватарки живут днями, а не секундами: с `no-store` они грузились бы
    // заново на каждом экране со списком людей.
    fetchMock.mockResolvedValue(
      new Response("img", {
        status: 200,
        headers: { "content-type": "image/png", "cache-control": "public, max-age=86400" },
      }),
    );

    const response = await onRequest(
      context(new Request("https://app.test/api/avatar/7")),
    );

    expect(response.headers.get("cache-control")).toBe("public, max-age=86400");
  });

  it("передаёт тело запроса дальше (загрузки не буферизуются)", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 201 }));

    const request = new Request("https://app.test/api/push", {
      method: "POST",
      body: '{"token":"x"}',
      headers: { "content-type": "application/json" },
    });

    await onRequest(context(request));

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBe(request.body);
  });

  it("честно отвечает 502, когда апстрим недоступен", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));

    const response = await onRequest(context(new Request("https://app.test/api/me")));

    expect(response.status).toBe(502);
    // Один и тот же код — чтобы клиент мог отличить «прокси лежит» от
    // ответа бэкенда и показать понятный текст.
    expect(await response.json()).toEqual({ detail: "proxy_unavailable" });
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
});
