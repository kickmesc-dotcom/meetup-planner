import { expect, test, type Page } from "@playwright/test";
import { mockApi, seedSession } from "./api";

/**
 * Chaos-прогон (этап 5, `docs/AAA_ROADMAP.md`).
 *
 * Проверяем не «приложение работает», а «приложение не врёт и не показывает
 * белый экран», когда всё плохо: API недоступен, сессия протухла, сеть еле
 * дышит, отправка оборвалась. Именно в этих состояниях человек либо понимает,
 * что произошло, либо уходит навсегда.
 *
 * Моки те же, что в остальных e2e: боевой API не трогаем.
 */

/** Обрыв соединения: `route.abort("failed")` — это `TypeError: Failed to fetch`. */
async function blockApi(page: Page): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith("/api/")) return route.fallback();
    return route.abort("failed");
  });
}

test("API недоступен до входа: остаётся форма, а не белый экран", async ({ page }) => {
  await blockApi(page);
  await page.goto("/");

  await expect(page.locator('input[type="email"]')).toBeVisible();
  await expect(page.locator("h1")).toBeVisible();
  // Ни одного «сырого» текста движка: человек не должен читать «Failed to fetch».
  await expect(page.locator("body")).not.toContainText("Failed to fetch");
});

test("сессия протухла: 401 возвращает на вход, без цикла", async ({ page }) => {
  await mockApi(page); // здесь все ручки отвечают 401
  await seedSession(page);
  await page.goto("/");

  await expect(page.locator('input[type="email"]')).toBeVisible();
  await expect(page.locator('button[type="submit"]')).toBeVisible();
});

test("медленная сеть: сначала скелетон, потом форма", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith("/api/")) return route.fallback();
    // Задержка меньше таймаута fetch, но заметная: скелетон должен успеть
    // появиться, иначе человек видит пустоту и решает, что приложение умерло.
    await new Promise((resolve) => setTimeout(resolve, 1500));
    return route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "unauthorized" }),
    });
  });
  await page.goto("/");

  await expect(page.locator(".animate-pulse").first()).toBeVisible();
  await expect(page.locator('input[type="email"]')).toBeVisible({ timeout: 10_000 });
});

test("обрыв при отправке: понятная ошибка связи, введённое не пропало", async ({
  page,
}) => {
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const path = new URL(url).pathname;
    if (!path.startsWith("/api/")) return route.fallback();
    if (path === "/api/auth/login") return route.abort("failed");
    return route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "unauthorized" }),
    });
  });
  await page.goto("/");

  const email = page.locator('input[type="email"]');
  await email.fill("owner@example.com");
  await page.locator("#auth-password").fill("secret123");
  await page.locator('button[type="submit"]').click();

  // Текст — из `humanizeApiError`: «нет связи», а не техническое имя ошибки.
  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(/связ|интернет/i);
  await expect(email).toHaveValue("owner@example.com");
});
