import { expect, test } from "@playwright/test";

/**
 * Офлайн-старт (этап 1, `docs/AAA_ROADMAP.md`, восьмой e2e-сценарий).
 *
 * Что проверяем: после одного визита оболочка и вся сборка лежат в кеше
 * service worker, поэтому без сети приложение открывается, а не остаётся
 * белым экраном или на заставке.
 *
 * Почему без мока API: мок ответил бы и в офлайне, и проверка потеряла бы
 * смысл. Без сессии приложение показывает форму входа — это и есть первый
 * кадр, который раньше требовал сети.
 *
 * Почему новая страница, а не `reload()`: перезагрузка под эмуляцией офлайна
 * в Chromium уходит мимо service worker, и тест проверял бы сеть, а не кэш.
 *
 * Запуск: `npm run test:e2e:offline` (конфиг `playwright.offline.config.ts`),
 * потому что service worker работает только на собранной статике.
 */

test("офлайн-старт: оболочка и сборка из кэша, без запросов в сеть", async ({
  page,
  context,
}) => {
  await page.goto("/");
  // Без API приложение показывает форму входа — значит оболочка жива.
  await expect(page.getByRole("heading", { name: "Вход" })).toBeVisible({
    timeout: 30_000,
  });

  // Ждём, пока SW встанет и начнёт управлять страницей: `clients.claim()`
  // в `activate` делает это без перезагрузки, но не мгновенно.
  await page.waitForFunction(
    () =>
      "serviceWorker" in navigator &&
      navigator.serviceWorker.controller !== null,
    undefined,
    { timeout: 20_000 },
  );

  await context.setOffline(true);
  const offlinePage = await context.newPage();
  const failed: string[] = [];
  offlinePage.on("requestfailed", (request) => {
    if (request.url().includes("/assets/")) failed.push(request.url());
  });

  await offlinePage.goto("/");

  await expect(
    offlinePage.getByRole("heading", { name: "Вход" }),
  ).toBeVisible({ timeout: 20_000 });

  // Ни один файл сборки не должен был уйти в сеть: если precache неполный,
  // браузер запрашивает `vendor-*.js` и падает — приложение остаётся на
  // заставке. Эта проверка ловит именно такой неполный кеш.
  expect(failed).toEqual([]);

  await context.setOffline(false);
});
