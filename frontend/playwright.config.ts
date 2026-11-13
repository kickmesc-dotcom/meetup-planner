import { defineConfig } from "@playwright/test";

/**
 * E2E на локальном стенде (этап 1, `docs/AAA_ROADMAP.md`).
 *
 * Почему не против боевого API: тесты должны быть детерминированными и не
 * оставлять данных в клиентской организации. Все `/api/**` перехватываются в
 * `e2e/api.ts`, поэтому ни один запрос не уходит в Amvera.
 *
 * Почему порт 4174: 5173 занимает обычный `npm run dev`, и `reuseExistingServer`
 * иначе подключался бы к чужой сессии с другими правками.
 *
 * Почему локально `channel: "chrome"`: Chrome уже установлен на машине, и
 * скачивать второй браузер ради прогона не нужно. В CI ставится chromium
 * отдельным шагом (`npx playwright install --with-deps chromium`).
 */
export default defineConfig({
  testDir: "./e2e",
  // Офлайн-старт требует production-сборки: у него свой конфиг.
  testIgnore: /offline\.spec\.ts/,
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
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
