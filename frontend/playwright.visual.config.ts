import { defineConfig } from "@playwright/test";

/**
 * Пиксельная регрессия — отдельный конфиг, потому что эталон привязан к
 * окружению: в CI это контейнер `mcr.microsoft.com/playwright:v1.65.0-jammy`
 * (оттуда снят `*-linux.png`), локально — Chrome на Windows (`*-win32.png`).
 * Основная e2e-джоба visual не запускает: там другое окружение и другие
 * шрифты, и красный CI из-за сглаживания приучал бы игнорировать красный.
 *
 * Запуск: `npm run test:e2e:visual`.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /visual\.spec\.ts/,
  timeout: 60_000,
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "list" : "list",
  use: {
    baseURL: "http://127.0.0.1:4174",
    viewport: { width: 390, height: 844 },
    locale: "ru-RU",
    trace: "on-first-retry",
    ...(process.env.CI ? {} : { channel: "chrome" }),
  },
  webServer: {
    command: "npm run dev -- --port 4174 --strictPort",
    url: "http://127.0.0.1:4174",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
