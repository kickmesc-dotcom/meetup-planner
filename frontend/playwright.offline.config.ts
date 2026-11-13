import { defineConfig } from "@playwright/test";

/**
 * Офлайн-старт проверяется на собранной статике: service worker регистрируется
 * только в production (`import.meta.env.PROD`), а в dev он кешировал бы модули
 * Vite и правки перестали бы доезжать до браузера.
 *
 * Поэтому отдельный конфиг: `vite preview` раздаёт `dist`, порт отличается от
 * dev-стенда, и прогон не требует пересборки между тестами.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /offline\.spec\.ts/,
  timeout: 60_000,
  use: {
    baseURL: "http://127.0.0.1:4175",
    viewport: { width: 390, height: 844 },
    locale: "ru-RU",
    trace: "on-first-retry",
    ...(process.env.CI ? {} : { channel: "chrome" }),
  },
  webServer: {
    command: "npm run preview -- --port 4175 --strictPort",
    url: "http://127.0.0.1:4175",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
