import { expect, test } from "@playwright/test";
import { mockApi } from "./api";

/**
 * Сценарии без живого аккаунта: экран входа доступен до авторизации, а API
 * замокан. Проверяем то, что раньше ловилось только руками: обязательность,
 * объявление ошибки, переключение режима и языка, мобильную вёрстку.
 */
test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
});

test("форма входа: почта и пароль обязательны и подписаны для скринридера", async ({
  page,
}) => {
  const email = page.locator('input[type="email"]');
  await expect(email).toBeVisible();
  await expect(email).toHaveAttribute("aria-required", "true");
  await expect(page.locator("#auth-password")).toHaveAttribute(
    "aria-required",
    "true",
  );
  await expect(page.locator('button[type="submit"]')).toBeVisible();
});

test("пустая почта: ошибка объявлена и фокус уходит в поле", async ({ page }) => {
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole("alert")).toBeVisible();
  const email = page.locator('input[type="email"]');
  await expect(email).toHaveAttribute("aria-invalid", "true");
  await expect(email).toBeFocused();
});

test("отказ сервера: ошибка у формы, поля помечены aria-invalid", async ({
  page,
}) => {
  await page.locator('input[type="email"]').fill("owner@example.com");
  await page.locator("#auth-password").fill("secret123");
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole("alert")).toContainText(/парол/i);
  await expect(page.locator('input[type="email"]')).toHaveAttribute(
    "aria-invalid",
    "true",
  );
});

test("переход к восстановлению пароля убирает поле пароля", async ({ page }) => {
  await page.getByRole("button", { name: /Забыл/i }).click();
  await expect(page.locator("#auth-password")).toHaveCount(0);
  await expect(page.locator('input[type="email"]')).toBeVisible();
});

test("переключение языка меняет заголовок формы", async ({ page }) => {
  const heading = page.locator("h1");
  const before = await heading.textContent();
  await page.getByRole("button", { name: /EN/i }).first().click();
  await expect(heading).not.toHaveText(before ?? "");
});

test("мобильная ширина 390: нет горизонтального скролла", async ({ page }) => {
  const overflow = await page.evaluate(() => {
    const el = document.scrollingElement as HTMLElement | null;
    return el ? el.scrollWidth - window.innerWidth : 0;
  });
  expect(overflow).toBeLessThanOrEqual(1);
});
