import { expect, test } from "@playwright/test";
import { mockApi, mockSignedInApi } from "./api";

/**
 * Скриншот-регрессия ключевых экранов (этап 7 AAA).
 *
 * Почему база локальная, а в CI пропуск. Скриншот сравнивает пиксели, а они
 * зависят от шрифтов и сглаживания ОС: база, снятая на Windows/Chrome, на
 * ubuntu-раннере даст другой растр при верной вёрстке. Красный CI из-за шрифта
 * приучает игнорировать красный, поэтому здесь явный `skip` в CI и запись в
 * `docs/AAA_ROADMAP.md`: эталон переезжает в Linux-контейнер отдельным шагом.
 *
 * Почему 390×844 и 1280×900. Первый — боевой телефон (ширина Telegram Mini
 * App), второй — момент, когда включается `DesktopShell`. Между ними работает
 * обычная текучая вёрстка, её проверяет `layout.spec.ts`.
 *
 * Почему `animations: "disabled"` и `reducedMotion`. Вход экрана — 120 мс
 * opacity; без отключения снимок ловил бы промежуточный кадр. `reducedMotion`
 * выключает и framer-motion через `useReducedMotion`.
 */
const VIEWPORTS = [
  { name: "phone", width: 390, height: 844 },
  { name: "desktop", width: 1280, height: 900 },
] as const;

test.skip(Boolean(process.env.CI), "база снята на Windows; CI-эталон — после Linux-контейнера");

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.name} ${viewport.width}×${viewport.height}`, () => {
    test.use({
      viewport: { width: viewport.width, height: viewport.height },
      reducedMotion: "reduce",
    });

    test("вход", async ({ page }) => {
      await mockApi(page);
      await page.goto("/");
      await expect(page.locator("h1")).toBeVisible();
      await expect(page).toHaveScreenshot(`login-${viewport.name}.png`, {
        animations: "disabled",
        caret: "hide",
        maxDiffPixelRatio: 0.01,
      });
    });

    test("события", async ({ page }) => {
      await mockSignedInApi(page);
      await page.goto("/");
      await expect(page.getByRole("button", { name: /Профиль/i })).toBeVisible();
      await page.waitForTimeout(600);
      await expect(page).toHaveScreenshot(`feed-${viewport.name}.png`, {
        animations: "disabled",
        caret: "hide",
        maxDiffPixelRatio: 0.01,
      });
    });

    test("задачи", async ({ page }) => {
      await mockSignedInApi(page);
      await page.goto("/");
      await expect(page.getByRole("button", { name: /Профиль/i })).toBeVisible();
      await page.waitForTimeout(400);
      await page.getByRole("button", { name: /Задач/i }).first().click();
      await page.waitForTimeout(400);
      await expect(page).toHaveScreenshot(`tasks-${viewport.name}.png`, {
        animations: "disabled",
        caret: "hide",
        maxDiffPixelRatio: 0.01,
      });
    });
  });
}
