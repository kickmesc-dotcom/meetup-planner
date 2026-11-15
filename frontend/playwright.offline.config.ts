import { defineConfig } from "@playwright/test";

/**
 * Офлайн-старт проверяется на собранной статике: service worker регистрируется
 * только в production (`import.meta.env.PROD`), а в dev он кешировал бы модули
 * Vite и правки перестали бы доезжать до браузера.
 *
 * По умолчанию — `vite preview` на отдельном порту: прогон не требует
 * пересборки между тестами и не зависит от dev-стенда.
 *
 * Второй режим — живой адрес: `LIVE_BASE_URL=https://semitaskbot.pages.dev
 * npm run test:e2e:offline`. Тогда сервер не поднимается: проверяется ровно
 * тот service worker и тот precache, которые получил настоящий посетитель
 * после деплоя. Это единственный способ увидеть расхождение «локально офлайн
 * работает, на CDN — нет»: заголовки и список файлов на краю другие.
 */
const liveBaseURL = process.env.LIVE_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  testMatch: /offline\.spec\.ts/,
  timeout: 60_000,
  use: {
    baseURL: liveBaseURL ?? "http://127.0.0.1:4175",
    viewport: { width: 390, height: 844 },
    locale: "ru-RU",
    trace: "on-first-retry",
    ...(process.env.CI ? {} : { channel: "chrome" }),
  },
  webServer: liveBaseURL
    ? undefined
    : {
        command: "npm run preview -- --port 4175 --strictPort",
        url: "http://127.0.0.1:4175",
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
});
