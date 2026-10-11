// @vitest-environment jsdom
/**
 * GHG11(17/18): окно приёма ответа в админке — границы те же, что на сервере.
 *
 * Зажим живёт на клиенте, чтобы оператор не отправлял мусор, а бэкенд его всё
 * равно зажимает (`ACCEPT_WINDOW_MAX_MINUTES`) — здесь проверяем клиентскую часть,
 * чтобы обе границы совпадали по числам.
 */
import { describe, expect, it } from "vitest";
import { ACCEPT_WINDOW_MAX_MINUTES, clampAcceptWindow } from "./GameScreen";

describe("clampAcceptWindow", () => {
  it("0 — «как сейчас», его не подменяем каталогом", () => {
    expect(clampAcceptWindow(0)).toBe(0);
  });

  it("нормальные значения проходят как есть", () => {
    expect(clampAcceptWindow(180)).toBe(180);
    expect(clampAcceptWindow(480)).toBe(480);
  });

  it("потолок — сутки (как ACCEPT_WINDOW_MAX_MINUTES на сервере)", () => {
    expect(ACCEPT_WINDOW_MAX_MINUTES).toBe(1440);
    expect(clampAcceptWindow(99999)).toBe(1440);
  });

  it("отрицательное и мусор — ноль, а не отрицательное окно", () => {
    expect(clampAcceptWindow(-10)).toBe(0);
    expect(clampAcceptWindow(Number.NaN)).toBe(0);
    expect(clampAcceptWindow(Number.POSITIVE_INFINITY)).toBe(0);
  });

  it("дробные округляются до минуты", () => {
    expect(clampAcceptWindow(90.4)).toBe(90);
    expect(clampAcceptWindow(90.6)).toBe(91);
  });
});
