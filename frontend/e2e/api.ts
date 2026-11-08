import type { Page } from "@playwright/test";

/**
 * Ни один e2e-запрос не должен уйти в боевой API.
 *
 * Перехватываем весь `/api/**`: вход и регистрация отвечают ошибкой (это и
 * проверяем), запрос сброса пароля — успехом, остальное — 401. Стенд остаётся
 * детерминированным, а данные клиентской организации не трогаются.
 */
export async function mockApi(
  page: Page,
  options: { loginStatus?: number; loginDetail?: string } = {},
): Promise<void> {
  const failure = {
    status: options.loginStatus ?? 500,
    contentType: "application/json",
    body: JSON.stringify({
      detail: options.loginDetail ?? "Неверная почта или пароль",
    }),
  };

  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const path = new URL(url).pathname;
    // Шаблон ловит и модули Vite `/src/api/*.ts` — их отдаём дальше без
    // подмены, иначе приложение не загрузится и тест ищет форму в пустом DOM.
    if (!path.startsWith("/api/")) return route.fallback();
    if (url.includes("/api/auth/login")) return route.fulfill(failure);
    if (url.includes("/api/auth/register")) return route.fulfill(failure);
    if (url.includes("/api/auth/password/reset/request")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true }),
      });
    }
    return route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "unauthorized" }),
    });
  });
}
