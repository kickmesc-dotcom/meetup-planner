import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mockApi, mockSignedInApi } from "./api";

/**
 * Автоматическая проверка доступности (этап 2, `docs/AAA_ROADMAP.md`).
 *
 * Что проверяем: нарушения уровня serious/critical по WCAG 2.0/2.1 A и AA на
 * тех экранах, которые можно открыть без боевого аккаунта. Список внутренних
 * экранов ограничен данными мока: кабинет и экраны с записями требуют
 * демо-стенда, и это записано в плане, а не выдано за проверенное.
 *
 * Почему отдельный файл, а не «на каждый экран свой тест»: отчёт axe содержит
 * селекторы, и в падении важно видеть экран целиком, а не одну кнопку.
 */

async function scan(page: Page, screen: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  const report = serious
    .map((v) => {
      const nodes = v.nodes
        .slice(0, 3)
        .map((n) => `    ${n.target.join(" ")}`)
        .join("\n");
      return `${v.id} (${v.impact}: ${v.help})\n${nodes}`;
    })
    .join("\n");
  expect(report, `Экран «${screen}»`).toBe("");
}

// axe прогоняет полный DOM-обход в браузере: девять таких сканов разом
// душили один и тот же сервер и падали по таймауту. Внутри файла — по очереди,
// файлы по-прежнему параллельны.
test.describe.configure({ mode: "serial" });

test.describe("без входа", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
  });

  test("вход", async ({ page }) => {
    await expect(page.locator("h1")).toBeVisible();
    await scan(page, "вход");
  });

  test("регистрация", async ({ page }) => {
    await page.getByRole("button", { name: /Создать|Регистрац/i }).first().click();
    await expect(page.locator("h1")).toBeVisible();
    await scan(page, "регистрация");
  });

  test("восстановление пароля", async ({ page }) => {
    await page.getByRole("button", { name: /Забыл/i }).click();
    await expect(page.locator("h1")).toBeVisible();
    await scan(page, "восстановление пароля");
  });
});

test.describe("после входа", () => {
  test.beforeEach(async ({ page }) => {
    await mockSignedInApi(page);
    await page.goto("/");
    await expect(page.getByTestId("manage-tabbar").or(page.locator("nav").first())).toBeVisible();
  });

  test("события", async ({ page }) => {
    await scan(page, "события");
  });

  test("задачи", async ({ page }) => {
    await page.getByRole("button", { name: /Задач/i }).first().click();
    await scan(page, "задачи");
  });

  test("чек-лист", async ({ page }) => {
    await page.getByRole("button", { name: /Чек-лист|Чеклист/i }).first().click();
    await scan(page, "чек-лист");
  });

  test("табель", async ({ page }) => {
    await page.getByRole("button", { name: /График|Табель/i }).first().click();
    await scan(page, "табель");
  });

  test("профиль", async ({ page }) => {
    await page.getByRole("button", { name: /Профиль/i }).first().click();
    await scan(page, "профиль");
  });

  test("кабинет", async ({ page }) => {
    // Зоны переключаются `role="tab"`, а не кнопкой: это один контрол с
    // двумя состояниями, и скринридер объявляет выбранную зону.
    await page.getByRole("tab", { name: /Управление/i }).click();
    await expect(page.getByTestId("manage-zone")).toBeVisible();
    await scan(page, "кабинет");
  });
});
