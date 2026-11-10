import type { Page } from "@playwright/test";
import type { Bootstrap } from "../src/api/bootstrap";
import type { UiPrefs } from "../src/api/availability";
import type { HrEmployee, OrgSetup } from "../src/api/hr";
import type { User } from "../src/types";

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

/**
 * Данные «уже вошедшего» человека для проверок внутренних экранов без
 * настоящего аккаунта и без боевой базы.
 *
 * Это ровно то, что отдаёт `GET /api/bootstrap`, плюс пустые ответы на всё
 * остальное: экраны получают форму, шапку и навигацию, но не выдуманные
 * данные, которые пришлось бы поддерживать в тесте.
 */
const ME: User = {
  id: 1,
  telegram_id: 100001,
  display_name: "E2E Владелец",
  username: "e2e",
  avatar_url: null,
  email: "e2e@example.com",
  email_verified: true,
  color_hex: "#5288c1",
  timezone: "Europe/Moscow",
  created_at: "2026-01-01T00:00:00.000Z",
  is_admin: false,
};

const EMPLOYEE: HrEmployee = {
  id: 1,
  user_id: 1,
  display_name: "E2E Владелец",
  telegram_id: 100001,
  department_id: 1,
  department_name: "Зал",
  position: "Управляющий",
  badge: null,
  badge_emoji: null,
  role: "admin",
  experience: "experienced",
  onboarding_state: "done",
  learning_mode: false,
  is_aup: true,
  is_admin: true,
  is_staff: true,
  is_active: true,
  is_demo: false,
  profile_public: true,
  show_last_seen: true,
  show_last_media: true,
  can_toggle_last_seen: true,
  can_toggle_last_media: true,
  profile_locked: false,
  last_seen_at: null,
};

const ORG: OrgSetup = {
  done: true,
  industry: "hoReCa",
  headcount: "10-30",
  departments: ["Зал"],
  sections: [
    "shifts",
    "team",
    "review",
    "reports",
    "issues",
    "handovers",
    "standards",
    "materials",
    "links",
    "calendar",
    "meetings",
  ],
  profile_visibility: "colleagues",
  cross_department_watch: false,
  allow_hide_last_seen: true,
  allow_hide_media: true,
  uz_pack: false,
  presets: [],
  positions: [],
  can_edit: true,
  can_manage_packs: false,
};

const PREFS: UiPrefs = {
  hide_greeting: false,
  welcome_format: "both",
  muted_feed: [],
  show_last_seen: true,
};

export const BOOTSTRAP: Bootstrap = {
  me: ME,
  users: [ME],
  employee: EMPLOYEE,
  tasks: [],
  org_setup: ORG,
  ui_prefs: PREFS,
};

/** Сессия по почте: приложение считает человека вошедшим до первого запроса. */
export async function seedSession(page: Page): Promise<void> {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("semitask.session_token", "e2e-token");
    } catch {
      // приватный режим — не мешает проверке, вход просто не сохранится
    }
  });
}

/** Авторизованный стенд: старт из `BOOTSTRAP`, остальное — пустые ответы. */
export async function mockSignedInApi(page: Page): Promise<void> {
  await seedSession(page);
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith("/api/")) return route.fallback();
    const json = (body: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (path === "/api/bootstrap") return json(BOOTSTRAP);
    if (path === "/api/me") return json(ME);
    if (path === "/api/users") return json([ME]);
    if (path === "/api/me/employee") return json(EMPLOYEE);
    if (path === "/api/org-setup") return json(ORG);
    if (path === "/api/me/ui-prefs") return json(PREFS);
    if (path === "/api/meta") return json({ ok: true });
    // Лента и её фильтры — объекты, а не списки: с пустым `[]` экран читает
    // `filters.departments.find` у `undefined` и падает в `ErrorBoundary`.
    if (path === "/api/feed/filters") {
      return json({
        scope: "all",
        can_filter: false,
        kinds: [],
        employees: [],
        departments: [],
      });
    }
    if (path === "/api/feed") {
      return json({ items: [], can_filter: false, scope: "all" });
    }
    // Остальное — пустой список: экранам достаточно формы и навигации, а
    // выдуманные записи пришлось бы поддерживать вместе с разметкой.
    return json([]);
  });
}
