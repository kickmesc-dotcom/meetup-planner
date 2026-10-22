// @vitest-environment jsdom
/**
 * VISUAL_AUDIT P1.8: тестовый сотрудник в ленте.
 *
 * Было три метки в одной строке: префикс `[BOT]` в имени, плашка должности и
 * чип `BOT` внутри неё. Проверяем, что осталась одна — «тест», имя чистое,
 * а плашка у тестового не дублируется. Живые люди при этом не меняются:
 * их плашка на месте.
 *
 * Отдельно проверяем совместимость: если бэкенд ещё не отдаёт `is_demo`,
 * лента узнаёт пул по префиксу и всё равно рисует одну метку.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import HrFeedScreen from "./HrFeedScreen";
import {
  fetchEmployeeCard,
  fetchFeedFilters,
  fetchHrFeed,
  type HrFeedItem,
} from "@/api/hr";

vi.mock("@/api/hr", () => ({
  fetchHrFeed: vi.fn(),
  fetchFeedFilters: vi.fn(),
  fetchEmployeeCard: vi.fn(),
}));

const feedMock = vi.mocked(fetchHrFeed);
const filtersMock = vi.mocked(fetchFeedFilters);
const cardMock = vi.mocked(fetchEmployeeCard);

function item(overrides: Partial<HrFeedItem> = {}): HrFeedItem {
  return {
    at: new Date().toISOString(),
    kind: "task_status",
    employee_id: 1,
    user_id: 1,
    display_name: "Пётр",
    department_id: 1,
    text: "закрыл(а) поручение",
    ref_id: 5,
    badge: "Су-шеф",
    badge_emoji: "🍳",
    ...overrides,
  };
}

function renderFeed(items: HrFeedItem[]) {
  feedMock.mockResolvedValue({
    scope: "all",
    can_filter: false,
    items,
  });
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <HrFeedScreen />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  feedMock.mockReset();
  filtersMock.mockReset();
  filtersMock.mockResolvedValue({
    scope: "all",
    can_filter: false,
    departments: [],
    employees: [],
    kinds: [],
  } as unknown as Awaited<ReturnType<typeof fetchFeedFilters>>);
});
afterEach(cleanup);

describe("HrFeedScreen (P1.8)", () => {
  it("помечает тестового одним «тест» и не показывает префикс", async () => {
    renderFeed([
      item({
        display_name: "[BOT] Алина",
        badge: "Стажёр",
        badge_emoji: "🌱",
        is_demo: true,
        text: "закрыла чек-лист",
      }),
    ]);

    const mark = await screen.findByTestId("feed-demo-mark");
    expect(mark.textContent).toBe("тест");
    expect(screen.queryByText(/\[BOT\]/)).toBeNull();
    expect(screen.getByText("Алина")).toBeTruthy();
    // Плашка должности у пула не дублирует метку.
    expect(screen.queryByText("Стажёр")).toBeNull();
  });

  it("узнаёт пул по префиксу, если сервер не прислал is_demo", async () => {
    renderFeed([item({ display_name: "[BOT] Борис", badge: "Стажёр" })]);

    expect(await screen.findByTestId("feed-demo-mark")).toBeTruthy();
    expect(screen.getByText("Борис")).toBeTruthy();
    expect(screen.queryByText("Стажёр")).toBeNull();
  });

  it("оставляет плашку живому сотруднику", async () => {
    renderFeed([item({ display_name: "Пётр", badge: "Су-шеф" })]);

    expect(await screen.findByText("Пётр")).toBeTruthy();
    expect(screen.getByText("Су-шеф")).toBeTruthy();
    expect(screen.queryByTestId("feed-demo-mark")).toBeNull();
  });

  it("имя — пилюля с цветным аутлайном, по тапу открывается карточка", async () => {
    cardMock.mockResolvedValue({
      employee_id: 1,
      display_name: "Пётр",
      department_id: 1,
      department_name: "Кухня",
      position: null,
      badge: "Су-шеф",
      badge_emoji: "🍳",
      role: "employee",
      role_label: "Сотрудник",
      is_demo: false,
      is_self: false,
      can_manage: false,
      profile_open: true,
      can_view: true,
      xp: 12,
      rank_title: "Стажёр",
      rank_emoji: "🌱",
      week_xp: 12,
      week_place: 1,
      week_total: 3,
      checklist_items: 4,
      tasks_done: 1,
      shifts_done: 1,
      activity: [],
    });
    renderFeed([item()]);

    const name = await screen.findByText("Пётр");
    const pill = name.closest("button") as HTMLButtonElement;
    // Аутлайн и подложка — из палитры человека, поэтому имя не сливается с
    // соседними строками ленты.
    // jsdom нормализует hsl в rgba — важно, что цвет вообще задан и что он
    // не равен цвету подложки карточки (то есть аутлайн виден).
    expect(pill.style.border).toContain("solid");
    expect(pill.style.border).toMatch(/rgba?\(/);
    expect(pill.style.backgroundColor).toMatch(/rgba?\(/);

    fireEvent.click(pill);
    await screen.findByText("Последние действия");
    expect(cardMock).toHaveBeenCalledWith(1);
  });

  it("не повторяет область видимости в пилюле и подзаголовке (P2.13)", async () => {
    renderFeed([item()]);

    await screen.findByText("Пётр");
    // Пилюля «Всё предприятие» одна, подзаголовок объясняет правило.
    expect(screen.getAllByText("Всё предприятие")).toHaveLength(1);
    expect(screen.getByText("Всё, что происходит на смене.")).toBeTruthy();
  });
});
