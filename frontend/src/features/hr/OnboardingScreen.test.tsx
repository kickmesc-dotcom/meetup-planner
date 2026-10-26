// @vitest-environment jsdom
/**
 * Новый сотрудник: последний шаг знакомства — «Первая смена», не курс.
 *
 * Почему это проверяется. Репетиция первого запуска от лица бариста-новичка
 * показала: на входе в приложение он получал список из семи уроков, счётчик
 * «0/7» и кнопку «Сбросить прогресс обучения» — и делал из этого вывод, что от
 * него требуют что-то уже знать. Здесь три обещания:
 *
 *  - вместо стены уроков видно три вещи, которые спросит первая смена;
 *  - «Открыть смену» закрывает знакомство и НЕ трогает режим обучения (его
 *    выбирают в профиле, а не на первом экране);
 *  - курс никуда не делся: он открывается кнопкой, по желанию.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import OnboardingScreen from "./OnboardingScreen";
import {
  fetchDepartments,
  submitOnboarding,
  type HrEmployee,
} from "@/api/hr";

vi.mock("@/api/hr", () => ({
  fetchDepartments: vi.fn(),
  submitOnboarding: vi.fn(),
}));
// Курс — отдельный экран со своими запросами; здесь важно лишь то, что он
// открывается по кнопке, а не то, что внутри.
vi.mock("@/features/hr/TrainingScreen", () => ({
  default: () => <div>экран-курса</div>,
}));
vi.mock("@/tg/webapp", () => ({
  haptic: vi.fn(),
  showAlert: vi.fn(),
  showConfirm: vi.fn(),
}));

const departmentsMock = vi.mocked(fetchDepartments);
const submitMock = vi.mocked(submitOnboarding);

function employee(overrides: Partial<HrEmployee> = {}): HrEmployee {
  return {
    id: 1,
    display_name: "Азиз",
    badge: "Стажёр",
    badge_emoji: "🌱",
    is_demo: false,
    role: "employee",
    position: "Бариста",
    department_id: 1,
    department_name: "Бариста",
    experience: "new",
    learning_mode: false,
    // Знакомство дошло до последнего шага — того самого, где был курс.
    onboarding_state: "training",
    is_admin: false,
    is_staff: false,
    is_aup: false,
    ...overrides,
  } as HrEmployee;
}

function renderScreen(overrides: Partial<HrEmployee> = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <OnboardingScreen employee={employee(overrides)} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  departmentsMock.mockReset();
  submitMock.mockReset();
  departmentsMock.mockResolvedValue([
    { id: 1, name: "Бариста", emoji: "☕" },
  ] as Awaited<ReturnType<typeof fetchDepartments>>);
  submitMock.mockResolvedValue(employee({ onboarding_state: "done" }));
});
afterEach(cleanup);

describe("OnboardingScreen: первая смена", () => {
  it("показывает три вещи вместо стены уроков", () => {
    renderScreen();

    expect(screen.getByText("Первая смена")).toBeTruthy();
    expect(screen.getByText("Чек-лист смены")).toBeTruthy();
    expect(screen.getByText("Поручения")).toBeTruthy();
    expect(screen.getByText("Закрытие смены")).toBeTruthy();
    // Курс не открыт: он по кнопке.
    expect(screen.queryByText("экран-курса")).toBeNull();
  });

  it("не пугает новичка сбросом прогресса на входе", () => {
    renderScreen();

    expect(screen.queryByText("Сбросить прогресс обучения")).toBeNull();
    expect(screen.queryByText("Я уже запомнил")).toBeNull();
  });

  it("«Открыть смену» закрывает знакомство, не меняя режим обучения", async () => {
    renderScreen();

    fireEvent.click(screen.getByRole("button", { name: "Открыть смену" }));

    await vi.waitFor(() => expect(submitMock).toHaveBeenCalledTimes(1));
    // Именно без `learning_mode`: выбор режима живёт в профиле, а не здесь.
    expect(submitMock).toHaveBeenCalledWith({ finish: true });
  });

  it("курс открывается по кнопке и умеет закрыть знакомство", async () => {
    renderScreen();

    fireEvent.click(
      screen.getByRole("button", { name: "Хочу посмотреть, как всё устроено" }),
    );

    expect(screen.getByText("экран-курса")).toBeTruthy();
    expect(screen.getByText("Как устроено приложение")).toBeTruthy();
    // Кнопки первого экрана уступили место курсу — двух конкурирующих
    // «продолжить» на экране не остаётся.
    expect(screen.queryByRole("button", { name: "Открыть смену" })).toBeNull();
  });

  it("кто уже ответил на шаги — попадает сразу на первую смену", () => {
    renderScreen({ onboarding_state: "training", department_id: null });

    // Отдел не выбран — строка с подразделением просто не показывается.
    expect(screen.getByText("Первая смена")).toBeTruthy();
    expect(screen.queryByText(/Бариста ·/)).toBeNull();
  });
});
