// @vitest-environment jsdom
/**
 * GHG11(17): окно приёма вариантов в админке — границы те же, что на сервере.
 *
 * Зажим живёт на клиенте, чтобы оператор не отправлял мусор, а бэкенд его всё
 * равно зажимает (`VOICE_WINDOW_MAX_MINUTES`) — здесь проверяем клиентскую часть,
 * чтобы обе границы совпадали по числам.
 */
import { describe, expect, it } from "vitest";
import { VOICE_WINDOW_MAX_MINUTES, clampVoiceWindow } from "./GameScreen";

describe("clampVoiceWindow", () => {
  it("0 — «как сейчас», его не подменяем каталогом", () => {
    expect(clampVoiceWindow(0)).toBe(0);
  });

  it("нормальные значения проходят как есть", () => {
    expect(clampVoiceWindow(180)).toBe(180);
    expect(clampVoiceWindow(480)).toBe(480);
  });

  it("потолок — сутки (как VOICE_WINDOW_MAX_MINUTES на сервере)", () => {
    expect(VOICE_WINDOW_MAX_MINUTES).toBe(1440);
    expect(clampVoiceWindow(99999)).toBe(1440);
  });

  it("отрицательное и мусор — ноль, а не отрицательное окно", () => {
    expect(clampVoiceWindow(-10)).toBe(0);
    expect(clampVoiceWindow(Number.NaN)).toBe(0);
    expect(clampVoiceWindow(Number.POSITIVE_INFINITY)).toBe(0);
  });

  it("дробные округляются до минуты", () => {
    expect(clampVoiceWindow(90.4)).toBe(90);
    expect(clampVoiceWindow(90.6)).toBe(91);
  });
});
