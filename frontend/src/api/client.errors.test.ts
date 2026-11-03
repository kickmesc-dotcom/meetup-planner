// @vitest-environment jsdom
/**
 * Коды лимитов организации в человеческий текст (B2B_PLATFORM_PLAN, шаг 5.3).
 *
 * Зачем отдельный тест. Сервер отдаёт машиночитаемый `detail`, а экран обязан
 * показать объяснение: `org_rate_limited:42` в алерте читается как поломка.
 * Проверяем именно ветки перевода — их легко потерять при правке
 * `humanizeApiError`, и тогда клиент увидит сырой код.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("@/tg/webapp", () => ({ getInitData: vi.fn(() => "") }));

import { ApiError, humanizeApiError } from "./client";

describe("humanizeApiError: лимиты организации", () => {
  it("переводит лимит частоты и сохраняет секунды", () => {
    const text = humanizeApiError(new ApiError(429, "org_rate_limited:42"));
    expect(text).toContain("42");
    expect(text).toContain("тариф");
    expect(text).not.toContain("org_rate_limited");
  });

  it("не путает лимит организации с лимитом по адресу", () => {
    // У периметра свой код; у организации — свой. Один перевод на два случая
    // сказал бы клиенту «подожди», когда дело в купленном тарифе.
    expect(humanizeApiError(new ApiError(429, "rate_limited:7"))).not.toContain(
      "тариф выше",
    );
    expect(humanizeApiError(new ApiError(429, "org_rate_limited:7"))).toContain(
      "тариф выше",
    );
  });

  it("объясняет исчерпанное место, а не «битый файл»", () => {
    const text = humanizeApiError(new ApiError(413, "storage_full"));
    expect(text).toContain("Место для фото");
    expect(text).not.toContain("storage_full");
  });
});
