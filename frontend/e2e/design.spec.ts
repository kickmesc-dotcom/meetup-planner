import { expect, test, type Page } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { mockApi, mockSignedInApi } from "./api";

/**
 * Дизайн-снимок ключевых экранов (этап 7 AAA, DoD «визуальные диффы ловятся CI»).
 *
 * Почему не пиксели. Растровый снимок зависит от шрифтов и сглаживания ОС:
 * база с Windows на ubuntu-раннере не совпадёт при верной вёрстке. Поэтому
 * здесь фиксируется то, что от платформы не зависит, — computed-стили и
 * высота целей: размер и вес шрифта, цвет текста и фона, радиус, отступы,
 * высота кнопок и полосы. Если кто-то поменяет токен, «незаметно» сдвинет
 * палитру или сломает 44 px, дифф появится в CI.
 *
 * Пиксельная база (`visual.spec.ts`) остаётся для локальной приёмки: она
 * ловит то, чего стили не видят (перекрытия, обрезку), но в CI пропускается
 * до появления Linux-эталона.
 *
 * Обновление базы: `UPDATE_DESIGN=1 npx playwright test e2e/design.spec.ts`.
 */
const BASELINE = new URL("./design-baseline.json", import.meta.url);

const SELECTORS = {
  heading: "h1",
  nav: "nav",
  activeTab: 'nav [aria-current="page"]',
  modeSwitch: '[data-testid="mode-switch"]',
} as const;

const PROPS = [
  "font-size",
  "font-weight",
  "letter-spacing",
  "color",
  "background-color",
  "border-radius",
  "padding-top",
  "padding-bottom",
] as const;

type Snapshot = Record<string, Record<string, string | number> | null>;

async function snapshot(page: Page): Promise<Snapshot> {
  return page.evaluate(
    ({ selectors, props }) => {
      const result: Record<string, Record<string, string | number> | null> = {};
      for (const [name, selector] of Object.entries(selectors)) {
        const node = document.querySelector<HTMLElement>(selector);
        if (!node) {
          result[name] = null;
          continue;
        }
        const style = getComputedStyle(node);
        const values: Record<string, string | number> = {};
        for (const prop of props) values[prop] = style.getPropertyValue(prop);
        // Ширину не фиксируем: она зависит от текста и шрифта. Высота — да:
        // именно она держит тач-цель 44 px и полосу 48 px.
        values.height = Math.round(node.getBoundingClientRect().height);
        result[name] = values;
      }
      return result;
    },
    { selectors: SELECTORS, props: PROPS },
  );
}

test("дизайн-снимок: вход, события, задачи", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale: "ru-RU",
    reducedMotion: "reduce",
  });

  const result: Record<string, Snapshot> = {};

  const login = await context.newPage();
  await mockApi(login);
  await login.goto("/");
  await expect(login.locator("h1")).toBeVisible({ timeout: 15_000 });
  result.login = await snapshot(login);
  await login.close();

  const app = await context.newPage();
  await mockSignedInApi(app);
  await app.goto("/");
  await expect(app.getByRole("button", { name: /Профиль/i })).toBeVisible({
    timeout: 15_000,
  });
  await app.waitForTimeout(600);
  result.feed = await snapshot(app);

  await app.getByRole("button", { name: /Задач/i }).first().click();
  await app.waitForTimeout(400);
  result.tasks = await snapshot(app);
  await app.close();
  await context.close();

  if (process.env.UPDATE_DESIGN === "1") {
    writeFileSync(BASELINE, `${JSON.stringify(result, null, 2)}\n`);
    return;
  }

  const baseline = JSON.parse(readFileSync(BASELINE, "utf8")) as typeof result;
  expect(result).toEqual(baseline);
});
