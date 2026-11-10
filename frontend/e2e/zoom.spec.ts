import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockSignedInApi } from "./api";

/**
 * §1.4.4 `resize-text` / `dynamic-type`: 200 % текста без потери содержимого.
 *
 * Почему так, а не браузерным зумом. Браузерный зум масштабирует и медиа, и
 * вьюпорт; на телефоне он к тому же недоступен как отдельное действие. Нам
 * важно другое: человек увеличил системный шрифт, и вёрстка на rem не должна
 * разъезжаться. Поэтому поднимаем корневой размер вдвое — ровно то, что
 * приложение получит от настройки ОС.
 *
 * Что считаем ошибкой: документ шире вьюпорта (горизонтальная прокрутка) и
 * элемент, вылезший за правый край. Скрытый `overflow-x` не спасает — контент
 * всё равно обрезан, поэтому смотрим геометрию, а не `scrollWidth`.
 */
// Последовательный режим: девять браузерных контекстов разом давали
// detached-кнопки на медленном прогоне — это шум стенда, а не дефект
// вёрстки. Проверки по одному остаются теми же.
test.describe.configure({ mode: "serial" });

async function zoomText(page: Page): Promise<void> {
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "32px";
  });
  await page.waitForTimeout(250);
}

async function overflowingText(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const width = window.innerWidth;
    const offenders: string[] = [];
    for (const node of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      const style = getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") continue;
      if (style.position === "fixed") continue;
      const rect = node.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      // Декоративные свечения и фоновые слои выходят за край осознанно.
      if (style.pointerEvents === "none" && node.getAttribute("aria-hidden") === "true") continue;
      if (rect.right > width + 1) {
        const label = node.textContent?.trim().slice(0, 40) ?? "";
        offenders.push(`${node.tagName.toLowerCase()}.${node.className.toString().slice(0, 60)} «${label}»`);
      }
    }
    return offenders.slice(0, 8);
  });
}

async function check(page: Page, screen: string): Promise<void> {
  await zoomText(page);
  const offenders = await overflowingText(page);
  expect(offenders, `Экран «${screen}» при 200 % текста`).toEqual([]);
}

test.describe("200 % текста, без входа", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
  });

  test("вход", async ({ page }) => {
    await expect(page.locator("h1")).toBeVisible();
    await check(page, "вход");
  });

  test("регистрация", async ({ page }) => {
    await page.getByRole("button", { name: /Создать|Регистрац/i }).first().click();
    await expect(page.locator("h1")).toBeVisible();
    await check(page, "регистрация");
  });

  test("восстановление пароля", async ({ page }) => {
    await page.getByRole("button", { name: /Забыл/i }).click();
    await expect(page.locator("h1")).toBeVisible();
    await check(page, "восстановление пароля");
  });
});

test.describe("200 % текста, после входа", () => {
  test.beforeEach(async ({ page }) => {
    await mockSignedInApi(page);
    await page.goto("/");
    await expect(page.locator("nav").first()).toBeVisible();
    // Навигация появляется раньше, чем приходит bootstrap: между первым и
    // полным рендером шапка перемонтируется, и клик по вкладке в этот момент
    // получает detached-элемент. Ждём вкладку профиля и короткую паузу.
    await expect(page.getByRole("button", { name: /Профиль/i })).toBeVisible();
    await page.waitForTimeout(400);
  });

  test("события", async ({ page }) => {
    await check(page, "события");
  });

  test("задачи", async ({ page }) => {
    await page.getByRole("button", { name: /Задач/i }).first().click();
    await check(page, "задачи");
  });

  test("чек-лист", async ({ page }) => {
    await page.getByRole("button", { name: /Чек-лист|Чеклист/i }).first().click();
    await check(page, "чек-лист");
  });

  test("график", async ({ page }) => {
    await page.getByRole("button", { name: /График|Табель/i }).first().click();
    await check(page, "график");
  });

  test("профиль", async ({ page }) => {
    await page.getByRole("button", { name: /Профиль/i }).first().click();
    await check(page, "профиль");
  });

  test("кабинет", async ({ page }) => {
    await page.getByRole("tab", { name: /Управление/i }).click();
    await expect(page.getByTestId("manage-zone")).toBeVisible();
    await check(page, "кабинет");
  });
});
