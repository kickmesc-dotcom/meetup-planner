/**
 * Адреса и тела запросов у обёрток `api()`.
 *
 * Зачем такие тесты. Типы проверяют форму ответа, но не путь: лишний сегмент
 * или забытый `POST` собираются без ошибок и отвечают 404 уже на боевом
 * сервере. Именно так случилось с пакетом отрасли (см. `packs.test.ts`).
 * Здесь проверяется контракт, который видит сервер: метод, путь, тело.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.fn();

vi.mock("./client", () => ({ api: (...args: unknown[]) => apiMock(...args) }));
vi.mock("@/tg/webapp", () => ({ getInitData: () => "" }));

import { createAccessLink, fetchAccessLinks, revokeAccessLink } from "./access";
import {
  confirmEmailVerification,
  confirmPasswordReset,
  fetchDevices,
  loginRequest,
  logoutAllRequest,
  logoutRequest,
  registerRequest,
  requestEmailVerification,
  requestPasswordReset,
  revokeDevice,
} from "./auth";
import {
  createRange,
  deleteRange,
  fetchMe,
  fetchRanges,
  fetchUiPrefs,
  fetchUsers,
  patchRange,
  updateUiPrefs,
} from "./availability";
import {
  fetchBirthdayGreeting,
  fetchBirthdaysInWindow,
  fetchCalendarMarks,
  fetchChukhanHistory,
  fetchCurrentTitles,
  fetchCurrentWorm,
  fetchLoserReason,
  fetchScheduledGames,
  fetchWormHistory,
  postBirthdayGreeting,
} from "./birthdays";
import {
  createAdminChecklist,
  createAdminHall,
  createChecklistItem,
  deleteChecklistItem,
  fetchAdminChecklists,
  fetchAdminHalls,
  patchAdminChecklist,
  patchAdminHall,
  patchChecklistItem,
} from "./checklists";

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockResolvedValue(undefined);
});

describe("access links", () => {
  it("читает список без токенов в пути", async () => {
    await fetchAccessLinks();
    expect(apiMock).toHaveBeenCalledWith("/api/me/access-links");
  });

  it("создаёт ссылку с подписью по умолчанию", async () => {
    await createAccessLink();
    expect(apiMock).toHaveBeenCalledWith("/api/me/access-links", {
      method: "POST",
      body: JSON.stringify({ label: "Открыть на компьютере" }),
    });
  });

  it("отзывает ссылку по id", async () => {
    await revokeAccessLink(7);
    expect(apiMock).toHaveBeenCalledWith("/api/me/access-links/7", {
      method: "DELETE",
    });
  });
});

describe("auth", () => {
  it("входит по почте и паролю", async () => {
    await loginRequest("owner@example.com", "secret123");
    expect(apiMock).toHaveBeenCalledWith("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: "owner@example.com",
        password: "secret123",
      }),
    });
  });

  it("регистрирует с именем и без него", async () => {
    await registerRequest("a@b.ru", "secret123", "  Иван  ");
    expect(apiMock).toHaveBeenLastCalledWith("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email: "a@b.ru",
        password: "secret123",
        display_name: "Иван",
      }),
    });

    await registerRequest("a@b.ru", "secret123");
    const body = JSON.parse(apiMock.mock.calls.at(-1)?.[1].body as string);
    expect(body.display_name).toBeNull();
  });

  it("гасит одну сессию и все сразу", async () => {
    await logoutRequest();
    expect(apiMock).toHaveBeenLastCalledWith("/api/auth/logout", {
      method: "POST",
    });
    await logoutAllRequest();
    expect(apiMock).toHaveBeenLastCalledWith("/api/auth/logout-all", {
      method: "POST",
    });
  });

  it("читает устройства и отзывает одно", async () => {
    await fetchDevices();
    expect(apiMock).toHaveBeenLastCalledWith("/api/auth/sessions");
    await revokeDevice(4);
    expect(apiMock).toHaveBeenLastCalledWith("/api/auth/sessions/4", {
      method: "DELETE",
    });
  });

  it("запрашивает и подтверждает сброс пароля", async () => {
    await requestPasswordReset("a@b.ru");
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/auth/password/reset/request",
      { method: "POST", body: JSON.stringify({ email: "a@b.ru" }) },
    );
    await confirmPasswordReset("tok", "newpass12");
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/auth/password/reset/confirm",
      {
        method: "POST",
        body: JSON.stringify({ token: "tok", password: "newpass12" }),
      },
    );
  });

  it("запрашивает и подтверждает адрес почты", async () => {
    await requestEmailVerification();
    expect(apiMock).toHaveBeenLastCalledWith("/api/auth/email/verify/request", {
      method: "POST",
    });
    await confirmEmailVerification("tok");
    expect(apiMock).toHaveBeenLastCalledWith("/api/auth/email/verify/confirm", {
      method: "POST",
      body: JSON.stringify({ token: "tok" }),
    });
  });
});

describe("availability и профиль", () => {
  it("читает себя и список участников", async () => {
    await fetchMe();
    expect(apiMock).toHaveBeenLastCalledWith("/api/me");
    await fetchUsers();
    expect(apiMock).toHaveBeenLastCalledWith("/api/users");
  });

  it("читает и правит предпочтения интерфейса", async () => {
    await fetchUiPrefs();
    expect(apiMock).toHaveBeenLastCalledWith("/api/me/ui-prefs");
    await updateUiPrefs({ hide_greeting: true });
    expect(apiMock).toHaveBeenLastCalledWith("/api/me/ui-prefs", {
      method: "PUT",
      body: JSON.stringify({ hide_greeting: true }),
    });
  });

  it("передаёт окно дат в ISO", async () => {
    const from = new Date("2026-11-08T00:00:00.000Z");
    const to = new Date("2026-11-15T00:00:00.000Z");
    await fetchRanges(from, to);
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/availability?from=2026-11-08T00:00:00.000Z&to=2026-11-15T00:00:00.000Z",
    );
  });

  it("создаёт, правит и удаляет интервал", async () => {
    const body = { starts_at: "2026-11-08T09:00:00Z", ends_at: "2026-11-08T18:00:00Z" };
    await createRange(body as never);
    expect(apiMock).toHaveBeenLastCalledWith("/api/availability", {
      method: "POST",
      body: JSON.stringify(body),
    });
    await patchRange(5, { note: "полдня" } as never);
    expect(apiMock).toHaveBeenLastCalledWith("/api/availability/5", {
      method: "PATCH",
      body: JSON.stringify({ note: "полдня" }),
    });
    await deleteRange(5);
    expect(apiMock).toHaveBeenLastCalledWith("/api/availability/5", {
      method: "DELETE",
    });
  });
});

describe("birthdays и календарь", () => {
  const from = new Date("2026-11-01T00:00:00.000Z");
  const to = new Date("2026-11-30T00:00:00.000Z");

  it("читает дни рождения в окне", async () => {
    await fetchBirthdaysInWindow(from, to);
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/birthdays/calendar?from=2026-11-01T00:00:00.000Z&to=2026-11-30T00:00:00.000Z",
    );
  });

  it("просит и публикует поздравление", async () => {
    await fetchBirthdayGreeting(3, "2026-11-08");
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/birthdays/3/greeting?date=2026-11-08",
      { method: "POST" },
    );
    await postBirthdayGreeting(3, "С днём!", true);
    expect(apiMock).toHaveBeenLastCalledWith("/api/birthdays/3/greeting/post", {
      method: "POST",
      body: JSON.stringify({ text: "С днём!", signed: true }),
    });
  });

  it("читает метки и причину ролла", async () => {
    await fetchCalendarMarks(from, to);
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/calendar/marks?from=2026-11-01T00:00:00.000Z&to=2026-11-30T00:00:00.000Z",
    );
    await fetchLoserReason("2026-11-08", 3);
    expect(apiMock).toHaveBeenLastCalledWith("/api/calendar/loser/2026-11-08/3");
  });

  it("читает звания и историю", async () => {
    await fetchCurrentWorm();
    expect(apiMock).toHaveBeenLastCalledWith("/api/worm/current");
    await fetchCurrentTitles();
    expect(apiMock).toHaveBeenLastCalledWith("/api/titles/current");
    await fetchChukhanHistory();
    expect(apiMock).toHaveBeenLastCalledWith("/api/chukhan/history?limit=20");
    await fetchChukhanHistory(5);
    expect(apiMock).toHaveBeenLastCalledWith("/api/chukhan/history?limit=5");
    await fetchWormHistory(3);
    expect(apiMock).toHaveBeenLastCalledWith("/api/worm/history?limit=3");
  });

  it("читает запланированные игры в окне", async () => {
    await fetchScheduledGames(from, to);
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/games/scheduled?from=2026-11-01T00:00:00.000Z&to=2026-11-30T00:00:00.000Z",
    );
  });
});

describe("чек-листы администратора", () => {
  it("залы: список, создание, правка", async () => {
    await fetchAdminHalls();
    expect(apiMock).toHaveBeenLastCalledWith("/api/admin/halls");
    await createAdminHall("Основной");
    expect(apiMock).toHaveBeenLastCalledWith("/api/admin/halls", {
      method: "POST",
      body: JSON.stringify({ name: "Основной" }),
    });
    await patchAdminHall(1, { is_active: false });
    expect(apiMock).toHaveBeenLastCalledWith("/api/admin/halls/1", {
      method: "PATCH",
      body: JSON.stringify({ is_active: false }),
    });
  });

  it("шаблоны: список, создание, правка", async () => {
    await fetchAdminChecklists();
    expect(apiMock).toHaveBeenLastCalledWith("/api/admin/checklists");
    const created = { department_id: 2, title: "Открытие", kind: "shift" as const };
    await createAdminChecklist(created);
    expect(apiMock).toHaveBeenLastCalledWith("/api/admin/checklists", {
      method: "POST",
      body: JSON.stringify(created),
    });
    await patchAdminChecklist(2, { hall_id: null, hall_set: true });
    expect(apiMock).toHaveBeenLastCalledWith("/api/admin/checklists/2", {
      method: "PATCH",
      body: JSON.stringify({ hall_id: null, hall_set: true }),
    });
  });

  it("пункты: создание, правка, удаление", async () => {
    await createChecklistItem(2, { title: "Протереть столы" });
    expect(apiMock).toHaveBeenLastCalledWith("/api/admin/checklists/2/items", {
      method: "POST",
      body: JSON.stringify({ title: "Протереть столы" }),
    });
    await patchChecklistItem(9, { is_mandatory: true });
    expect(apiMock).toHaveBeenLastCalledWith("/api/admin/checklist-items/9", {
      method: "PATCH",
      body: JSON.stringify({ is_mandatory: true }),
    });
    await deleteChecklistItem(9);
    expect(apiMock).toHaveBeenLastCalledWith("/api/admin/checklist-items/9", {
      method: "DELETE",
    });
  });
});
