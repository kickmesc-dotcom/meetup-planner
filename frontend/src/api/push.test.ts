// @vitest-environment jsdom
/**
 * VAPID-ключ приходит из API строкой base64url, а подписка ждёт байты.
 * Ошибка здесь выглядит как «кнопка ничего не делает»: `atob` бросает на
 * `-`/`_`, и подписка молча не создаётся.
 */
import { describe, expect, it } from "vitest";
import { urlBase64ToUint8Array } from "./push";

function toBase64Url(bytes: number[]): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

describe("urlBase64ToUint8Array", () => {
  it("декодирует base64url без padding", () => {
    // 251/255 дают в base64 и `+`, и `/` — проверяем именно замену на `-`/`_`.
    const bytes = [251, 255, 0, 1, 2, 3];
    const decoded = urlBase64ToUint8Array(toBase64Url(bytes));
    expect(Array.from(decoded)).toEqual(bytes);
  });

  it("не падает на пустой строке", () => {
    expect(urlBase64ToUint8Array("").length).toBe(0);
  });

  it("возвращает байты в ArrayBuffer, а не view поверх SharedArrayBuffer", () => {
    // Иначе `PushManager.subscribe` отвергает ключ в браузере.
    expect(urlBase64ToUint8Array("AQID").buffer).toBeInstanceOf(ArrayBuffer);
  });
});
