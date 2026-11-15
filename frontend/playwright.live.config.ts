import { defineConfig } from "@playwright/test";

/**
 * E2E против ЖИВОГО адреса, а не локальной сборки.
 *
 * Зачем отдельный конфиг. Основной стенд поднимает dev-сервер и проверяет код
 * из рабочей копии; здесь проверяется то, что реально отдаёт CDN: другой
 * бандл, другие заголовки, другой service worker. Это ловит расхождения,
 * которые локальный прогон не видит по определению.
 *
 * Почему без `webServer`: сервер уже есть — это и есть смысл проверки.
 *
 * Почему API всё равно безопасен: `e2e/api.ts` перехватывает `**\/api/**`
 * на уровне браузера, поэтому ни один запрос не уходит в боевой бэкенд и
 * данные клиентской организации не меняются. Поэтому здесь нет ни логина,
 * ни записи — только те же моки, что и на локальном стенде.
 *
 * Адрес задаётся `LIVE_BASE_URL` (по умолчанию — прод). Превью конкретного
 * деплоя: `LIVE_BASE_URL=https://<hash>.semitaskbot.pages.dev npm run test:e2e:live`.
 */
const baseURL = process.env.LIVE_BASE_URL ?? "https://semitaskbot.pages.dev";

export default defineConfig({
  testDir: "./e2e",
  // У офлайн-старта и пиксельной регрессии свои конфиги: первый требует
  // управления service worker на локальном сервере, вторая привязана к
  // эталону окружения.
  testIgnore: [/offline\.spec\.ts/, /visual\.spec\.ts/],
  timeout: 30_000,
  fullyParallel: true,
  // Живой CDN отвечает не так ровно, как локальный сервер: один повтор
  // отделяет сетевую случайность от настоящей поломки.
  retries: 1,
  workers: 2,
  reporter: "list",
  use: {
    baseURL,
    viewport: { width: 390, height: 844 },
    locale: "ru-RU",
    trace: "on-first-retry",
    ...(process.env.CI ? {} : { channel: "chrome" }),
  },
});
