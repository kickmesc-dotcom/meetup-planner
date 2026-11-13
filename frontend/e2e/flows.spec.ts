import { expect, test } from "@playwright/test";
import { mockSignedInApi } from "./api";

/**
 * Сквозные сценарии внутренней части (этап 1, `docs/AAA_ROADMAP.md`).
 *
 * До этого файла e2e проверял вход, ошибки и доступность отдельных экранов,
 * но не то, что человек может открыть полноэкранный оверлей и вернуться туда,
 * откуда пришёл. Здесь этот маршрут: настройки профиля поверх вкладки.
 *
 * Раздел кабинета («Поручения») снимается отдельно, на production-сборке:
 * в dev `StrictMode` монтирует кабинет дважды, и ленивый чанк залипает в
 * скелетоне. На собранном бандле сценарий проходит.
 *
 * Стенд — мок из `e2e/api.ts`: боевая база не трогается, данные не заводятся.
 */

test.beforeEach(async ({ page }) => {
  await mockSignedInApi(page);
  await page.goto("/");
  // Полный каркас появляется после `/api/bootstrap`: до него вкладки ещё нет.
  await expect(page.getByRole("button", { name: /Профиль/i })).toBeVisible();
});

test("профиль: настройки открываются и закрываются системной «назад»", async ({
  page,
}) => {
  await page.getByRole("button", { name: /Профиль/i }).first().click();
  await expect(page.getByText("E2E Владелец").first()).toBeVisible();

  await page.getByRole("button", { name: /^Настройки/ }).click();
  await expect(
    page.getByRole("heading", { name: "Настройки", exact: true }),
  ).toBeVisible();

  // «Назад» закрывает оверлей, а не уводит с профиля: человек возвращается
  // туда, откуда открыл настройки.
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Настройки", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("E2E Владелец").first()).toBeVisible();
});
