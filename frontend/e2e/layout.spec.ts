import { expect, test, type Page } from "@playwright/test";
import { mockSignedInApi } from "./api";

/**
 * §6 `layout-breakpoints` (этап 7 AAA): вёрстка держится на 375, 768 и 1024.
 *
 * Почему именно эти ширины. 375 — самый узкий живой телефон (iPhone SE/mini),
 * 768 — планшет в портрете, 1024 — момент, когда включается `DesktopShell` и
 * появляется сайдбар. Между ними ничего не проверяем: если нет переполнения в
 * трёх точках перелома, его не будет и в промежутке, потому что все три макета
 * текучие.
 *
 * Что считаем дефектом: документ шире вьюпорта или элемент, вылезший за правый
 * край. `overflow-x: hidden` не маскирует — контент всё равно обрезан, поэтому
 * смотрим геометрию, как в `zoom.spec.ts`. Декоративные слои с `aria-hidden` и
 * `pointer-events: none` пропускаем: они выходят за край осознанно.
 */

const WIDTHS = [375, 768, 1024] as const;

async function overflow(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const width = window.innerWidth;
    const offenders: string[] = [];
    if (document.documentElement.scrollWidth > width + 1) {
      offenders.push(`документ: ${document.documentElement.scrollWidth} > ${width}`);
    }
    for (const node of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      const style = getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") continue;
      if (style.position === "fixed") continue;
      if (style.pointerEvents === "none" && node.getAttribute("aria-hidden") === "true") continue;
      const rect = node.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      if (rect.right > width + 1) {
        const label = node.textContent?.trim().slice(0, 40) ?? "";
        offenders.push(
          `${node.tagName.toLowerCase()}.${node.className.toString().slice(0, 50)} «${label}»`,
        );
      }
    }
    return offenders.slice(0, 6);
  });
}

async function openApp(page: Page): Promise<void> {
  await mockSignedInApi(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: /Профиль/i })).toBeVisible();
  await page.waitForTimeout(400);
}

test.describe("ширины 375 / 768 / 1024", () => {
  // Последовательный режим: девять контекстов разом давали detached-кнопки на
  // медленном прогоне — это шум стенда, а не дефект вёрстки (см. zoom.spec.ts).
  test.describe.configure({ mode: "serial" });

  for (const width of WIDTHS) {
    test(`события, задачи и профиль на ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width <= 390 ? 844 : 900 });
      await openApp(page);
      expect(await overflow(page), `события @ ${width}`).toEqual([]);

      await page.getByRole("button", { name: /Задач/i }).first().click();
      await page.waitForTimeout(300);
      expect(await overflow(page), `задачи @ ${width}`).toEqual([]);

      await page.getByRole("button", { name: /Профиль/i }).first().click();
      await page.waitForTimeout(300);
      expect(await overflow(page), `профиль @ ${width}`).toEqual([]);
    });
  }
});
