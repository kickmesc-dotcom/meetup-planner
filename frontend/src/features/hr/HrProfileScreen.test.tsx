// @vitest-environment jsdom
/**
 * VISUAL_AUDIT P1.7: профиль разгружен.
 *
 * Проверяем обещания новой структуры:
 *  - «Все разделы» свёрнуты по умолчанию и раскрываются одним нажатием;
 *  - в списке нет разделов, которые уже есть в нижней полосе (иначе два входа
 *    в одно место — на что и жаловался аудит);
 *  - админ-инструменты (примерка роли, режим проверки) не занимают место у
 *    обычного сотрудника и свёрнуты у админа.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import HrProfileScreen from "./HrProfileScreen";
import {
  fetchAdminEmployees,
  fetchDepartments,
  fetchEmployee,
  fetchTraining,
  type HrEmployee,
} from "@/api/hr";

vi.mock("@/api/hr", () => ({
  fetchEmployee: vi.fn(),
  fetchDepartments: vi.fn(),
  fetchTraining: vi.fn(),
  fetchOrgSetup: vi.fn(),
  setProfilePrivacy: vi.fn(),
  fetchAdminEmployees: vi.fn(),
  submitOnboarding: vi.fn(),
  switchMyRole: vi.fn(),
}));
vi.mock("@/api/simulation", () => ({ startSimulation: vi.fn() }));
vi.mock("@/api/texts", () => ({
  useAppText: (_key: string, fallback: string) => fallback,
}));
// Свои запросы/KPI и оверлеи — не предмет этого теста.
vi.mock("@/features/hr/KpiCard", () => ({ default: () => null }));
vi.mock("@/features/hr/AchievementsCard", () => ({ default: () => null }));
vi.mock("@/features/hr/TrainingScreen", () => ({ default: () => null }));
vi.mock("@/features/hr/FeedbackScreen", () => ({ default: () => null }));
vi.mock("@/features/hr/HrDemoPanel", () => ({ default: () => null }));

const employeeMock = vi.mocked(fetchEmployee);
const departmentsMock = vi.mocked(fetchDepartments);
const trainingMock = vi.mocked(fetchTraining);
const employeesMock = vi.mocked(fetchAdminEmployees);

function me(overrides: Partial<HrEmployee> = {}): HrEmployee {
  return {
    id: 1,
    display_name: "Пётр",
    badge: "Стажёр",
    badge_emoji: "🌱",
    is_demo: false,
    role: "employee",
    position: "Официант",
    department_id: 1,
    department_name: "Зал",
    experience: "new",
    learning_mode: false,
    onboarding_state: "done",
    is_admin: false,
    is_staff: false,
    is_aup: false,
    ...overrides,
  } as HrEmployee;
}

function renderScreen() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <HrProfileScreen />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  employeeMock.mockReset();
  departmentsMock.mockReset();
  trainingMock.mockReset();
  employeesMock.mockReset();
  departmentsMock.mockResolvedValue([
    { id: 1, name: "Зал", emoji: "🍽" },
  ] as Awaited<ReturnType<typeof fetchDepartments>>);
  trainingMock.mockResolvedValue({
    done: 1,
    total: 9,
    complete: false,
    lessons: [],
  } as unknown as Awaited<ReturnType<typeof fetchTraining>>);
  employeesMock.mockResolvedValue([]);
});
afterEach(cleanup);

describe("HrProfileScreen (P1.7)", () => {
  it("держит разделы свёрнутыми и не дублирует нижнюю полосу", async () => {
    employeeMock.mockResolvedValue(me());
    renderScreen();

    await screen.findByText("Пётр");
    // Свёрнуто: пунктов списка в DOM нет.
    expect(screen.queryByText("Материалы смены")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Все разделы/ }));

    expect(screen.getByText("Материалы смены")).toBeTruthy();
    expect(screen.getByText("График")).toBeTruthy();
    // Дубли таб-бара не показываем: задачи, смены, табель и события уже внизу.
    for (const label of [
      "Мои задачи",
      "Чек-лист смены",
      "Табель смен",
      "События смены",
      "Команда",
    ]) {
      expect(screen.queryByText(label)).toBeNull();
    }
    // Старой сетки «Быстрые переходы» больше нет.
    expect(screen.queryByText("Быстрые переходы")).toBeNull();
  });

  it("не показывает админ-инструменты обычному сотруднику", async () => {
    employeeMock.mockResolvedValue(me());
    renderScreen();

    await screen.findByText("Пётр");
    expect(screen.queryByText("Для администратора")).toBeNull();
    expect(screen.queryByText("Примерить роль")).toBeNull();
  });

  it("управляющему без подразделения показывает доступ, а не «не выбрано» (P2.15)", async () => {
    employeeMock.mockResolvedValue(
      me({
        role: "admin",
        is_admin: true,
        is_staff: true,
        is_aup: true,
        department_id: null,
        department_name: null,
        experience: null,
      }),
    );
    renderScreen();

    await screen.findByText("Пётр");
    expect(screen.getByText("Доступ")).toBeTruthy();
    expect(screen.getByText("все подразделения")).toBeTruthy();
    expect(screen.queryByText("не выбрано")).toBeNull();
    expect(screen.queryByText("не указан")).toBeNull();
    // Опыт для staff-роли не изображаем: это не брошенная анкета.
    expect(screen.queryByText("Опыт")).toBeNull();
  });

  it("сворачивает админ-инструменты у админа", async () => {
    employeeMock.mockResolvedValue(
      me({ role: "admin", is_admin: true, is_staff: true, is_aup: true }),
    );
    renderScreen();

    await screen.findByText("Пётр");
    expect(screen.queryByText("Примерить роль")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Для администратора/ }));

    expect(screen.getByText("Примерить роль")).toBeTruthy();
    expect(screen.getByText("Режим проверки")).toBeTruthy();
  });
});
