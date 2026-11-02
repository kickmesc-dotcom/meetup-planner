// @vitest-environment jsdom
/**
 * Витрина демо-данных в кабинете (план, фаза 3, шаг 3.3).
 *
 * Что проверяем и почему:
 *  - экран говорит, под какую ОТРАСЛЬ набран пул: иначе демо салона с поварами
 *    читается как ошибка, а не как витрина;
 *  - «завести демо» и «сгенерировать смены» — разные действия: показать надо
 *    сначала людей, потом активность;
 *  - удаление демо-людей требует подтверждения и передаёт `delete_employees`,
 *    потому что эта кнопка трогает строки, а не только следы.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fetchDemoState,
  purgeDemo,
  seedDemoPool,
  simulateDemo,
  type HrDemoState,
} from "@/api/hr";

vi.mock("@/api/hr", () => ({
  fetchDemoState: vi.fn(),
  seedDemoPool: vi.fn(),
  simulateDemo: vi.fn(),
  purgeDemo: vi.fn(),
  setDemoVisible: vi.fn(),
}));

vi.mock("@/tg/webapp", () => ({
  haptic: vi.fn(),
  showAlert: vi.fn(() => Promise.resolve()),
  showConfirm: vi.fn(() => Promise.resolve(true)),
}));

import DemoScreen from "./DemoScreen";

const STATE: HrDemoState = {
  visible: true,
  prefix: "[BOT]",
  industry: "salon",
  industry_title: "Салон красоты",
  employees: [
    {
      employee_id: 1,
      telegram_id: 900000000,
      display_name: "[BOT] Алина",
      badge: "Мастер",
      badge_emoji: "✂️",
      department_id: 3,
      department_name: "Парикмахеры",
      is_active: true,
    },
  ],
  activity: { checklist_runs: 4, tasks: 2, feedback_answers: 1 },
};

const EMPTY: HrDemoState = {
  ...STATE,
  employees: [],
  activity: { checklist_runs: 0, tasks: 0, feedback_answers: 0 },
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DemoScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(fetchDemoState).mockResolvedValue(STATE);
  vi.mocked(seedDemoPool).mockResolvedValue(STATE);
  vi.mocked(simulateDemo).mockResolvedValue({
    checklist_runs: 4,
    tasks: 2,
    task_events: 6,
    task_photos: 1,
    task_issues: 1,
    checklist_completions: 9,
    feedback_answers: 1,
  });
  vi.mocked(purgeDemo).mockResolvedValue({ tasks: 2 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DemoScreen", () => {
  it("показывает отрасль демо и что в нём уже есть", async () => {
    renderScreen();

    await screen.findByText("Демо «Салон красоты»");
    expect(screen.getByText("Людей: 1")).toBeTruthy();
    expect(screen.getByText("Чек-листов: 4")).toBeTruthy();
    expect(screen.getByText(/Парикмахеры/)).toBeTruthy();
  });

  it("заводит демо-сотрудников из отраслевого пакета", async () => {
    renderScreen();
    await screen.findByText("Демо «Салон красоты»");

    fireEvent.click(screen.getByText("Обновить состав демо"));

    await waitFor(() => expect(seedDemoPool).toHaveBeenCalled());
  });

  it("на пустом демо предлагает завести людей и не даёт генерировать смены", async () => {
    vi.mocked(fetchDemoState).mockResolvedValue(EMPTY);
    renderScreen();

    const seed = await screen.findByText("Завести демо-сотрудников");
    expect(seed).toBeTruthy();
    const simulate = screen.getByText("Сгенерировать активность за 3 смены");
    expect((simulate.closest("button") as HTMLButtonElement).disabled).toBe(true);
  });

  it("удаляет демо-людей только после подтверждения", async () => {
    const { showConfirm } = await import("@/tg/webapp");
    renderScreen();
    await screen.findByText("Демо «Салон красоты»");

    fireEvent.click(screen.getByText("Удалить демо-сотрудников"));

    await waitFor(() => expect(showConfirm).toHaveBeenCalled());
    await waitFor(() => expect(purgeDemo).toHaveBeenCalledWith(true));
  });
});
