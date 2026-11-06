// @vitest-environment jsdom
/**
 * «Настройки» — одна дверь к личным настройкам (06.11.2026).
 *
 * Проверяем то, из-за чего экран и появился: все пять тем на одном экране,
 * рабочее имя меняется, уведомления включаются по одному, а деньги видит
 * только руководитель.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MySettingsScreen from "./MySettingsScreen";
import {
  fetchEmployee,
  fetchNotifyPrefs,
  setMyName,
  setNotifyPref,
  type HrEmployee,
} from "@/api/hr";
import { useUI } from "@/store/ui";

vi.mock("@/api/hr", () => ({
  fetchEmployee: vi.fn(),
  fetchNotifyPrefs: vi.fn(),
  setMyName: vi.fn(),
  setNotifyPref: vi.fn(),
  setProfilePrivacy: vi.fn(),
  setProfileVisibility: vi.fn(),
}));
// Соседние карточки — не предмет этого теста.
vi.mock("@/features/hr/PushCard", () => ({ default: () => null }));
vi.mock("@/features/hr/FeedbackScreen", () => ({
  default: () => <div data-testid="feedback-overlay" />,
}));
vi.mock("@/components/LanguageSwitcher", () => ({ default: () => null }));
vi.mock("@/components/ThemeSwitcher", () => ({ default: () => null }));

const meMock = vi.mocked(fetchEmployee);
const prefsMock = vi.mocked(fetchNotifyPrefs);
const nameMock = vi.mocked(setMyName);
const notifyMock = vi.mocked(setNotifyPref);

function me(overrides: Partial<HrEmployee> = {}): HrEmployee {
  return {
    id: 1,
    user_id: 1,
    display_name: "Пётр",
    telegram_id: 1001,
    badge: null,
    badge_emoji: null,
    is_demo: false,
    role: "employee",
    position: "Официант",
    department_id: 1,
    department_name: "Зал",
    experience: "new",
    learning_mode: false,
    onboarding_state: "done",
    profile_public: true,
    show_last_seen: true,
    show_last_media: true,
    can_toggle_last_seen: true,
    can_toggle_last_media: true,
    profile_locked: false,
    last_seen_at: null,
    is_admin: false,
    is_staff: false,
    is_aup: false,
    is_active: true,
    ...overrides,
  } as HrEmployee;
}

function renderScreen() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MySettingsScreen onClose={() => undefined} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  meMock.mockReset();
  prefsMock.mockReset();
  nameMock.mockReset();
  notifyMock.mockReset();
  useUI.setState({ mode: "staff", pendingAdminSection: null });
  meMock.mockResolvedValue(me());
  prefsMock.mockResolvedValue({
    prefs: [
      { kind: "digest", enabled: false },
      { kind: "deadline", enabled: false },
      { kind: "escalation", enabled: false },
    ],
    kinds: ["digest", "deadline", "escalation"],
  });
  nameMock.mockResolvedValue(me({ display_name: "Анна Петрова" }));
  notifyMock.mockResolvedValue({
    prefs: [
      { kind: "digest", enabled: true },
      { kind: "deadline", enabled: false },
      { kind: "escalation", enabled: false },
    ],
    kinds: ["digest", "deadline", "escalation"],
  });
});
afterEach(cleanup);

describe("MySettingsScreen", () => {
  it("держит все пять тем на одном экране", async () => {
    renderScreen();

    await screen.findByDisplayValue("Пётр");
    for (const title of [
      "Профиль",
      "Публичность профиля",
      "Уведомления",
      "Язык и вид",
      "Обратная связь",
    ]) {
      expect(screen.getByText(title)).toBeTruthy();
    }
  });

  it("меняет имя в приложении, а не имя из Telegram", async () => {
    renderScreen();

    const input = await screen.findByLabelText("Имя в приложении");
    fireEvent.change(input, { target: { value: "  Анна Петрова " } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(nameMock).toHaveBeenCalledWith("Анна Петрова"));
  });

  it("включает уведомление по одному, а не всё сразу", async () => {
    renderScreen();

    const digest = await screen.findByRole("switch", { name: "Сводка дня" });
    fireEvent.click(digest);

    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith("digest", true));
  });

  it("не показывает оплату сотруднику", async () => {
    renderScreen();

    await screen.findByDisplayValue("Пётр");
    expect(screen.queryByText("Оплата и тариф")).toBeNull();
    expect(screen.queryByText("Тариф и лимиты")).toBeNull();
  });

  it("показывает руководителю тариф и счета и ведёт в кабинет", async () => {
    meMock.mockResolvedValue(me({ role: "aup", is_aup: true }));
    renderScreen();

    await screen.findByText("Оплата и тариф");
    fireEvent.click(screen.getByText("Оплата и счета"));

    expect(useUI.getState().mode).toBe("manage");
    expect(useUI.getState().pendingAdminSection).toBe("billing");
  });
});
