/**
 * Адреса и тела запросов: бренд, передачи смены, интеграции, журнал проблем,
 * знания, материалы, встречи и меню.
 *
 * Проверяем то, что видит сервер, — метод, путь и тело. Опечатка в пути
 * собирается без ошибок типов и всплывает 404 на боевом сервере.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.fn();
vi.mock("./client", () => ({ api: (...args: unknown[]) => apiMock(...args) }));
vi.mock("@/tg/webapp", () => ({ getInitData: () => "" }));

import { fetchBrand, resetBrand, updateBrand } from "./brand";
import {
  acceptHandover,
  createHandover,
  fetchColleagues,
  fetchHandover,
  fetchHandovers,
  fetchHandoverPreview,
  fetchHandoverSummary,
  rejectHandover,
} from "./handovers";
import {
  createApiKey,
  createWebhook,
  deleteWebhook,
  fetchApiKeys,
  fetchDeliveries,
  fetchImportRuns,
  fetchWebhooks,
  revokeApiKey,
  updateWebhook,
} from "./integrations";
import {
  commentIssue,
  createIssue,
  fetchIssue,
  fetchIssues,
  setIssueStatus,
  updateIssue,
} from "./issues";
import { searchKnowledge } from "./knowledge";
import { fetchMaterials, refreshMaterial } from "./materials";
import {
  autoPick,
  cancelMeeting,
  createAutoPickPoll,
  createPoll,
  fetchIcalUrl,
  fetchLoserHistory,
  fetchLoserStats,
  fetchMeetings,
  fetchPolls,
  rollLoser,
  setRsvp,
} from "./meetings";
import {
  createMenuItem,
  deleteMenuItem,
  fetchMenu,
  updateMenuItem,
} from "./menu";

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockResolvedValue(undefined);
});

describe("brand", () => {
  it("читает бренд", async () => {
    await fetchBrand();
    expect(apiMock).toHaveBeenCalledWith("/api/brand");
  });

  it("правит и сбрасывает бренд организации", async () => {
    await updateBrand({ name: "Кофейня", color: "#123456" });
    expect(apiMock).toHaveBeenLastCalledWith("/api/org/brand", {
      method: "PATCH",
      body: JSON.stringify({ name: "Кофейня", color: "#123456" }),
    });
    await resetBrand();
    expect(apiMock).toHaveBeenLastCalledWith("/api/org/brand", {
      method: "DELETE",
    });
  });
});

describe("handovers", () => {
  it("читает сдачи с фильтром и лимитом", async () => {
    await fetchHandovers();
    expect(apiMock).toHaveBeenLastCalledWith("/api/handovers?box=all&limit=50");
    await fetchHandovers("incoming", 10);
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/handovers?box=incoming&limit=10",
    );
  });

  it("читает сводку, превью и коллег", async () => {
    await fetchHandoverSummary();
    expect(apiMock).toHaveBeenLastCalledWith("/api/handovers/summary");
    await fetchHandoverPreview();
    expect(apiMock).toHaveBeenLastCalledWith("/api/handovers/preview");
    await fetchColleagues();
    expect(apiMock).toHaveBeenLastCalledWith("/api/handovers/colleagues");
  });

  it("открывает сдачу и создаёт новую", async () => {
    await fetchHandover(3);
    expect(apiMock).toHaveBeenLastCalledWith("/api/handovers/3");
    await createHandover({ to_employee_id: 4, note: "ключи у стойки" });
    expect(apiMock).toHaveBeenLastCalledWith("/api/handovers", {
      method: "POST",
      body: JSON.stringify({ to_employee_id: 4, note: "ключи у стойки" }),
    });
  });

  it("принимает и возвращает сдачу", async () => {
    await acceptHandover(3);
    expect(apiMock).toHaveBeenLastCalledWith("/api/handovers/3/accept", {
      method: "POST",
      body: JSON.stringify({ note: null }),
    });
    await acceptHandover(3, "принял");
    expect(apiMock).toHaveBeenLastCalledWith("/api/handovers/3/accept", {
      method: "POST",
      body: JSON.stringify({ note: "принял" }),
    });
    await rejectHandover(3, "не сходится касса");
    expect(apiMock).toHaveBeenLastCalledWith("/api/handovers/3/reject", {
      method: "POST",
      body: JSON.stringify({ reason: "не сходится касса" }),
    });
  });
});

describe("integrations", () => {
  it("ключи: список, создание, отзыв", async () => {
    await fetchApiKeys();
    expect(apiMock).toHaveBeenLastCalledWith("/api/org/api-keys");
    await createApiKey("Биллинг", ["people.read"]);
    expect(apiMock).toHaveBeenLastCalledWith("/api/org/api-keys", {
      method: "POST",
      body: JSON.stringify({ name: "Биллинг", scopes: ["people.read"] }),
    });
    await revokeApiKey(2);
    expect(apiMock).toHaveBeenLastCalledWith("/api/org/api-keys/2", {
      method: "DELETE",
    });
  });

  it("вебхуки: список, создание, правка, удаление", async () => {
    await fetchWebhooks();
    expect(apiMock).toHaveBeenLastCalledWith("/api/org/webhooks");
    await createWebhook("https://example.com/hook", ["employee.created"]);
    expect(apiMock).toHaveBeenLastCalledWith("/api/org/webhooks", {
      method: "POST",
      body: JSON.stringify({
        url: "https://example.com/hook",
        events: ["employee.created"],
      }),
    });
    await updateWebhook(7, { is_active: false });
    expect(apiMock).toHaveBeenLastCalledWith("/api/org/webhooks/7", {
      method: "PATCH",
      body: JSON.stringify({ is_active: false }),
    });
    await deleteWebhook(7);
    expect(apiMock).toHaveBeenLastCalledWith("/api/org/webhooks/7", {
      method: "DELETE",
    });
  });

  it("читает доставки и прогоны импорта", async () => {
    await fetchDeliveries();
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/org/webhooks/deliveries?limit=20",
    );
    await fetchDeliveries(5);
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/org/webhooks/deliveries?limit=5",
    );
    await fetchImportRuns();
    expect(apiMock).toHaveBeenLastCalledWith("/api/org/import-runs?limit=10");
  });
});

describe("issues", () => {
  it("без фильтров не добавляет пустой вопрос", async () => {
    await fetchIssues();
    expect(apiMock).toHaveBeenLastCalledWith("/api/issues");
  });

  it("собирает фильтры в строку запроса", async () => {
    await fetchIssues({
      statuses: ["open", "in_progress"],
      includeClosed: true,
      category: "it",
      mine: true,
      limit: 5,
    });
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/issues?statuses=open%2Cin_progress&include_closed=true&category=it&mine=true&limit=5",
    );
  });

  it("открывает, создаёт и правит проблему", async () => {
    await fetchIssue(4);
    expect(apiMock).toHaveBeenLastCalledWith("/api/issues/4");
    await createIssue({ title: "Течёт кран", severity: "high" });
    expect(apiMock).toHaveBeenLastCalledWith("/api/issues", {
      method: "POST",
      body: JSON.stringify({ title: "Течёт кран", severity: "high" }),
    });
    await updateIssue(4, { assignee_employee_id: 2, assignee_set: true });
    expect(apiMock).toHaveBeenLastCalledWith("/api/issues/4", {
      method: "PATCH",
      body: JSON.stringify({ assignee_employee_id: 2, assignee_set: true }),
    });
  });

  it("меняет статус и комментирует", async () => {
    await setIssueStatus(4, "resolved", "починили");
    expect(apiMock).toHaveBeenLastCalledWith("/api/issues/4/status", {
      method: "POST",
      body: JSON.stringify({ status: "resolved", comment: "починили" }),
    });
    await commentIssue(4, "жду мастера");
    expect(apiMock).toHaveBeenLastCalledWith("/api/issues/4/comments", {
      method: "POST",
      body: JSON.stringify({ text: "жду мастера" }),
    });
  });
});

describe("knowledge и materials", () => {
  it("кодирует запрос в поиске знаний", async () => {
    await searchKnowledge("график смен", 5);
    expect(apiMock).toHaveBeenLastCalledWith(
      `/api/knowledge/search?q=${encodeURIComponent("график смен")}&limit=5`,
    );
    await searchKnowledge("меню");
    expect(apiMock).toHaveBeenLastCalledWith(
      `/api/knowledge/search?q=${encodeURIComponent("меню")}&limit=12`,
    );
  });

  it("читает и обновляет материалы", async () => {
    await fetchMaterials();
    expect(apiMock).toHaveBeenLastCalledWith("/api/materials");
    await refreshMaterial(2);
    expect(apiMock).toHaveBeenLastCalledWith("/api/materials/2/refresh", {
      method: "POST",
    });
  });
});

describe("meetings и опросы", () => {
  const from = new Date("2026-11-08T00:00:00.000Z");
  const to = new Date("2026-11-09T00:00:00.000Z");

  it("читает встречи в окне и меняет ответ", async () => {
    await fetchMeetings(from, to);
    expect(apiMock).toHaveBeenLastCalledWith(
      "/api/meetings?from=2026-11-08T00:00:00.000Z&to=2026-11-09T00:00:00.000Z",
    );
    await setRsvp(9, 1);
    expect(apiMock).toHaveBeenLastCalledWith("/api/meetings/9/rsvp", {
      method: "PATCH",
      body: JSON.stringify({ rsvp: 1 }),
    });
    await cancelMeeting(9);
    expect(apiMock).toHaveBeenLastCalledWith("/api/meetings/9", {
      method: "DELETE",
    });
  });

  it("подбирает слот", async () => {
    const body = {
      window_start: "2026-11-08T09:00:00Z",
      window_end: "2026-11-08T18:00:00Z",
      duration_minutes: 30,
      step_minutes: 15,
      top_n: 3,
    };
    await autoPick(body);
    expect(apiMock).toHaveBeenLastCalledWith("/api/meetings/auto-pick", {
      method: "POST",
      body: JSON.stringify(body),
    });
  });

  it("крутит лоха и читает статистику", async () => {
    await rollLoser();
    expect(apiMock).toHaveBeenLastCalledWith("/api/loser/roll", {
      method: "POST",
    });
    await fetchLoserStats();
    expect(apiMock).toHaveBeenLastCalledWith("/api/loser/stats");
    await fetchLoserHistory();
    expect(apiMock).toHaveBeenLastCalledWith("/api/loser/history?limit=20");
    await fetchLoserHistory(5);
    expect(apiMock).toHaveBeenLastCalledWith("/api/loser/history?limit=5");
  });

  it("создаёт обычный и автоподобранный опрос", async () => {
    await createPoll({ question: "Когда встреча?", options: ["2026-11-09T10:00:00Z"] });
    expect(apiMock).toHaveBeenLastCalledWith("/api/polls", {
      method: "POST",
      body: JSON.stringify({
        question: "Когда встреча?",
        options: ["2026-11-09T10:00:00Z"],
      }),
    });
    await fetchPolls();
    expect(apiMock).toHaveBeenLastCalledWith("/api/polls");
    const auto = {
      window_start: "2026-11-08T09:00:00Z",
      window_end: "2026-11-08T18:00:00Z",
      duration_minutes: 30,
      step_minutes: 15,
      top_n: 3,
    };
    await createAutoPickPoll(auto);
    expect(apiMock).toHaveBeenLastCalledWith("/api/polls/auto-pick", {
      method: "POST",
      body: JSON.stringify(auto),
    });
  });

  it("отдаёт адрес календаря", async () => {
    await fetchIcalUrl();
    expect(apiMock).toHaveBeenLastCalledWith("/api/meetings/ical/url");
  });
});

describe("menu", () => {
  it("читает меню", async () => {
    await fetchMenu();
    expect(apiMock).toHaveBeenCalledWith("/api/menu");
  });

  it("создаёт, правит и удаляет блюдо", async () => {
    await createMenuItem({ name: "Суп", price_rub: 350 });
    expect(apiMock).toHaveBeenLastCalledWith("/api/menu", {
      method: "POST",
      body: JSON.stringify({ name: "Суп", price_rub: 350 }),
    });
    await updateMenuItem(6, { is_available: false });
    expect(apiMock).toHaveBeenLastCalledWith("/api/menu/6", {
      method: "PATCH",
      body: JSON.stringify({ is_available: false }),
    });
    await deleteMenuItem(6);
    expect(apiMock).toHaveBeenLastCalledWith("/api/menu/6", {
      method: "DELETE",
    });
  });
});
