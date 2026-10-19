// @vitest-environment jsdom
/**
 * Расписание обучения: карточка новичка, ставка и переключение дня.
 *
 * Проверяем ровно то, ради чего экран существует: видно текущую ставку и
 * сколько смен учебные; тап по дню отправляет противоположное значение;
 * переключение ставки уходит на сервер.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import TrainingPlanScreen from "./TrainingPlanScreen";
import {
  clearTrainingDay,
  fetchTrainingPlan,
  patchTrainingPlan,
  setTrainingDay,
  type HrTrainingPlan,
} from "@/api/hrTrainingPlan";

vi.mock("@/api/hrTrainingPlan", () => ({
  fetchTrainingPlan: vi.fn(),
  patchTrainingPlan: vi.fn(),
  setTrainingDay: vi.fn(),
  clearTrainingDay: vi.fn(),
}));

const fetchMock = vi.mocked(fetchTrainingPlan);
const patchMock = vi.mocked(patchTrainingPlan);
const dayMock = vi.mocked(setTrainingDay);
const clearMock = vi.mocked(clearTrainingDay);

const plan: HrTrainingPlan = {
  start: "2026-10-19",
  days: 2,
  rate_labels: { full: "Полная ставка", partial: "Частичная ставка" },
  items: [
    {
      employee_id: 7,
      user_id: 77,
      display_name: "Тест Новичок",
      position: "Повар",
      department_name: "Кухня",
      role: "employee",
      onboarding_state: "training",
      learning_mode: true,
      rate_type: "full",
      training_days: 2,
      hire_date: "2026-10-19",
      has_shifts: true,
      days: [
        {
          day: "2026-10-19",
          is_training: true,
          explicit: false,
          shift_status: "worked",
        },
        {
          day: "2026-10-20",
          is_training: true,
          explicit: true,
          shift_status: "planned",
        },
      ],
    },
  ],
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TrainingPlanScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  patchMock.mockReset();
  dayMock.mockReset();
  clearMock.mockReset();
  fetchMock.mockResolvedValue(plan);
  patchMock.mockResolvedValue(plan.items[0]);
  dayMock.mockResolvedValue({
    day: "2026-10-19",
    is_training: false,
    explicit: true,
    shift_status: "worked",
  });
  clearMock.mockResolvedValue({ cleared: true });
});
afterEach(cleanup);

describe("TrainingPlanScreen", () => {
  it("показывает ставку и число учебных смен", async () => {
    renderScreen();
    expect(await screen.findByText("Тест Новичок")).toBeTruthy();
    expect(screen.getByText("Полная ставка")).toBeTruthy();
    expect(screen.getByText("· учебных 2 из 2")).toBeTruthy();
  });

  it("тап по учебному дню отправляет «обычная»", async () => {
    renderScreen();
    fireEvent.click(await screen.findByText("Тест Новичок"));
    const chips = await screen.findAllByTitle(
      "Учебная смена — нажми, чтобы сделать обычной",
    );
    fireEvent.click(chips[0]);
    await waitFor(() =>
      expect(dayMock).toHaveBeenCalledWith(7, "2026-10-19", false),
    );
  });

  it("переключение ставки уходит на сервер", async () => {
    renderScreen();
    fireEvent.click(await screen.findByText("Тест Новичок"));
    fireEvent.click(await screen.findByText("Частичная ставка"));
    await waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith(7, { rate_type: "partial" }),
    );
  });

  it("ручное правило можно вернуть", async () => {
    renderScreen();
    fireEvent.click(await screen.findByText("Тест Новичок"));
    fireEvent.click(await screen.findByText("Вернуть правило"));
    await waitFor(() =>
      expect(clearMock).toHaveBeenCalledWith(7, "2026-10-20"),
    );
  });
});
