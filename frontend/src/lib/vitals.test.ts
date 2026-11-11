// @vitest-environment jsdom
/**
 * RUM: что именно уходит с устройства и как это классифицируется.
 *
 * Проверяем три вещи, из-за которых модуль и написан: устройство определяется
 * по Telegram, а не только по ширине окна; путь уходит без query; отправка не
 * зависит от того, доживёт ли страница до ответа (`keepalive`).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Metric } from "web-vitals";

vi.mock("@/api/client", () => ({ getApiBase: () => "https://api.test" }));
vi.mock("@/tg/webapp", () => ({
  WebApp: { platform: "", version: "" },
}));

import { deviceKind, platformName } from "./device";
import { buildVitalBody, sendVital } from "./vitals";

const fetchMock = vi.fn();

function metric(overrides: Partial<Metric> = {}): Metric {
  return {
    name: "LCP",
    value: 1234.5678,
    rating: "good",
    delta: 0,
    id: "v1-1",
    navigationType: "navigate",
    entries: [],
    ...overrides,
  } as unknown as Metric;
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(window, "innerWidth", { value: 1024, configurable: true });
});

describe("устройство", () => {
  it("узкое окно считается телефоном", () => {
    Object.defineProperty(window, "innerWidth", { value: 375, configurable: true });
    expect(deviceKind()).toBe("mobile");
  });

  it("широкое окно — компьютер", () => {
    Object.defineProperty(window, "innerWidth", { value: 1440, configurable: true });
    expect(deviceKind()).toBe("desktop");
  });

  it("вне Telegram платформа пустая, а не выдуманная", () => {
    expect(platformName()).toBe("");
  });
});

describe("отчёт", () => {
  it("несёт имя, округлённое значение, устройство и путь без query", () => {
    window.history.replaceState({}, "", "/app?access=SECRET");
    const body = buildVitalBody(metric(), "mobile");
    expect(body).toMatchObject({
      name: "LCP",
      value: 1234.568,
      rating: "good",
      device: "mobile",
      path: "/app",
    });
    expect(JSON.stringify(body)).not.toContain("SECRET");
  });

  it("отправляет метрику на приёмник с keepalive", () => {
    expect(sendVital(metric(), "desktop")).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.test/api/telemetry/vitals");
    expect(init).toMatchObject({ method: "POST", keepalive: true });
  });

  it("молчит, если сеть запрещена", () => {
    vi.stubGlobal("fetch", vi.fn(() => {
      throw new TypeError("Failed to fetch");
    }));
    expect(sendVital(metric(), "mobile")).toBe(false);
  });
});
