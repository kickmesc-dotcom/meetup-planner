// @vitest-environment jsdom
/**
 * PWA (B2B_PLATFORM_PLAN, шаг 2.3): установка на домашний экран и офлайн-старт.
 *
 * Проверяем то, что легко потерять при правках `index.html` или сборки:
 *  • манифест подключён и содержит обязательные поля;
 *  • есть иконки 192/512 и отдельная maskable (Android обрезает «any» в круг);
 *  • service worker не кеширует `/api/*` — устаревшие данные смены опаснее
 *    честной ошибки;
 *  • стартовый адрес и scope — корень, иначе установленное приложение
 *    открывается на пустой странице.
 *
 * Файлы читаются через `?raw` (как страж эмодзи): так тест не тянет `node:fs`
 * и работает в той же сборке Vite, что и приложение.
 */
import { describe, expect, it } from "vitest";
import manifestRaw from "../public/manifest.webmanifest?raw";
import swRaw from "../public/sw.js?raw";
import indexHtml from "../index.html?raw";

const manifest = JSON.parse(manifestRaw) as {
  name: string;
  short_name: string;
  start_url: string;
  scope: string;
  display: string;
  theme_color: string;
  background_color: string;
  icons: { src: string; sizes: string; purpose?: string }[];
};

describe("manifest", () => {
  it("ставится отдельным окном с корня", () => {
    expect(manifest.name).toContain("SemiTask");
    expect(manifest.short_name.length).toBeLessThanOrEqual(12);
    expect(manifest.start_url).toBe("/");
    expect(manifest.scope).toBe("/");
    expect(manifest.display).toBe("standalone");
  });

  it("цвета совпадают с темой приложения", () => {
    expect(manifest.theme_color).toBe("#1c6fb8");
    expect(manifest.background_color).toBe("#ffffff");
  });

  it("есть иконки 192, 512 и maskable", () => {
    const sizes = manifest.icons.map((icon) => icon.sizes);
    expect(sizes).toContain("192x192");
    expect(sizes).toContain("512x512");
    expect(
      manifest.icons.some((icon) => icon.purpose === "maskable"),
    ).toBe(true);
    for (const icon of manifest.icons) {
      expect(icon.src.startsWith("/")).toBe(true);
    }
  });
});

describe("index.html", () => {
  it("подключает манифест и иконки для установки", () => {
    expect(indexHtml).toContain('rel="manifest"');
    expect(indexHtml).toContain("/manifest.webmanifest");
    expect(indexHtml).toContain('rel="apple-touch-icon"');
    expect(indexHtml).toContain("apple-mobile-web-app-capable");
    expect(indexHtml).toContain('name="theme-color"');
  });
});

describe("service worker", () => {
  it("не кеширует данные смены", () => {
    expect(swRaw).toContain('"/api/"');
    expect(swRaw).toContain("request.method !== \"GET\"");
  });

  it("отдаёт оболочку при отсутствии сети", () => {
    expect(swRaw).toContain("networkFirst");
    expect(swRaw).toContain("/index.html");
    expect(swRaw).toContain("activate");
  });
});
