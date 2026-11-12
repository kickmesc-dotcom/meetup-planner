// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import { useLocale } from "@/i18n";

import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatNumber,
  formatTime,
} from "./format";

beforeEach(() => {
  useLocale.setState({ locale: "ru" });
});

describe("format", () => {
  it("деньги считаются в текущей локали", () => {
    expect(formatMoney(2900).replace(/\u00a0/g, " ")).toBe("2 900 ₽");
  });

  it("число без конечного значения — прочерк", () => {
    expect(formatNumber(Number.NaN)).toBe("—");
    expect(formatMoney(Number.POSITIVE_INFINITY)).toBe("—");
  });

  it("дата и время идут через Intl", () => {
    expect(formatDate("2026-11-12")).toBe("12.11.2026");
    expect(formatTime("2026-11-12T09:05:00")).toBe("09:05");
    expect(formatDateTime("2026-11-12T09:05:00")).toBe("12.11, 09:05");
  });

  it("битая дата не рисует Invalid Date", () => {
    expect(formatDate("not-a-date")).toBe("—");
    expect(formatDateTime("not-a-date")).toBe("—");
  });

  it("английская локаль меняет порядок даты", () => {
    useLocale.setState({ locale: "en" });
    expect(formatDate("2026-11-12")).toBe("12/11/2026");
  });
});
