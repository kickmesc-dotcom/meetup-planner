import { expect, test, type Page } from "@playwright/test";
import { mockSignedInApi } from "./api";

/**
 * §1.4.5 `touch-target-size` (этап 7 AAA): цель касания не меньше 44×44.
 *
 * Почему проверяем в браузере, а не в разметке. Половина кнопок получает
 * размер от родителя (`flex-1`, `grid place-items-center`), а часть — от
 * контента. Статический поиск `min-h-11` пропустил бы и «кнопку без класса,
 * растянутую флексом», и «кнопку с классом, но сжавшуюся в 20 px из-за
 * `px-0.5`». Нам важен итоговый прямоугольник.
 *
 * Что не считаем целью: строчные ссылки внутри абзаца (WCAG 2.5.5 прямо
 * делает для них исключение) и чекбоксы — их тач-целью служит `<label>`,
 * который лежит рядом и проверяется отдельно как кликабельная строка.
 */
async function undersized(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const offenders: string[] = [];
    const nodes = document.querySelectorAll<HTMLElement>(
      'button, [role="button"], a[href], input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]), select, textarea',
    );
    for (const node of nodes) {
      if (node.closest('[aria-hidden="true"]')) continue;
      // Skip-link — осознанно 1×1 до фокуса (`sr-only`), при Tab он
      // разворачивается в полноценную кнопку. Это не цель касания.
      if (node.matches('a[href="#main-content"]')) continue;
      const style = getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") continue;
      if (style.display === "inline" && node.tagName === "A") continue;
      if (node.matches(":disabled")) continue;
      const rect = node.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      if (rect.width < 44 || rect.height < 44) {
        const label =
          node.getAttribute("aria-label") ?? node.textContent?.trim().slice(0, 30) ?? "";
        offenders.push(
          `${node.tagName.toLowerCase()} ${Math.round(rect.width)}×${Math.round(rect.height)} «${label}»`,
        );
      }
    }
    return offenders.slice(0, 8);
  });
}

async function openApp(page: Page): Promise<void> {
  await mockSignedInApi(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: /Профиль/i })).toBeVisible();
  await page.waitForTimeout(400);
}

test.describe("тач-цели ≥ 44 px", () => {
  test("вход и регистрация", async ({ page }) => {
    // Без входа проверяем отдельно: там свои ссылки-переключатели режимов,
    // и они уходили в 20 px по высоте до этапа 2.
    await page.goto("/");
    await expect(page.locator("h1")).toBeVisible();
    expect(await undersized(page), "вход").toEqual([]);
  });

  test("события, задачи, чек-лист и профиль", async ({ page }) => {
    await openApp(page);
    for (const [tab, name] of [
      ["Задач", "задачи"],
      ["Чек-лист", "чек-лист"],
      ["Профиль", "профиль"],
    ] as const) {
      await page.getByRole("button", { name: new RegExp(tab, "i") }).first().click();
      await page.waitForTimeout(300);
      expect(await undersized(page), name).toEqual([]);
    }
  });
});
