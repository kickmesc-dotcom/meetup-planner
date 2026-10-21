// @vitest-environment jsdom
/**
 * Пул сотрудников: ручное заведение по ID и снапшоты состава.
 *
 * Проверяем два обещания экрана, которые нельзя увидеть глазами в коде:
 * мусор в поле ID не уходит на сервер (фильтр до цифр), а восстановление
 * снимка вызывает ручку именно того снимка, который нажали, и показывает
 * разбивку «заведено / возвращено / не тронуто».
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AddPersonPanel, RosterSnapshotsPanel } from "./RosterTools";
import {
  addEmployeeByTelegramId,
  createRosterSnapshot,
  fetchRosterSnapshots,
  restoreRosterSnapshot,
} from "@/api/hrOps";
import { showAlert, showConfirm } from "@/tg/webapp";

vi.mock("@/api/hrOps", () => ({
  addEmployeeByTelegramId: vi.fn(),
  createRosterSnapshot: vi.fn(),
  deleteRosterSnapshot: vi.fn(),
  fetchRosterSnapshots: vi.fn(),
  restoreRosterSnapshot: vi.fn(),
}));

vi.mock("@/api/hr", () => ({
  fetchDepartments: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/tg/webapp", () => ({
  haptic: vi.fn(),
  showAlert: vi.fn().mockResolvedValue(undefined),
  showConfirm: vi.fn().mockResolvedValue(true),
}));

const addMock = vi.mocked(addEmployeeByTelegramId);
const snapshotsMock = vi.mocked(fetchRosterSnapshots);
const restoreMock = vi.mocked(restoreRosterSnapshot);
const createMock = vi.mocked(createRosterSnapshot);
const alertMock = vi.mocked(showAlert);
const confirmMock = vi.mocked(showConfirm);

function renderPanel(node: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  confirmMock.mockResolvedValue(true);
  alertMock.mockResolvedValue(undefined);
});
afterEach(cleanup);

describe("AddPersonPanel", () => {
  it("отправляет только цифры из поля ID", async () => {
    addMock.mockResolvedValue({
      employee_id: 1,
      user_id: 2,
      display_name: "Аня",
      position: null,
      badge: null,
      badge_emoji: null,
      role: "employee",
      department_id: null,
      department_name: null,
      onboarding_state: "new",
      learning_mode: false,
      is_demo: false,
      is_active: true,
      fired_at: null,
      purge_after: null,
    });
    const onAdded = vi.fn();
    renderPanel(<AddPersonPanel onAdded={onAdded} />);

    fireEvent.click(screen.getByText("Добавить по Telegram ID"));
    const input = screen.getByPlaceholderText("например, 123456789");
    fireEvent.change(input, { target: { value: "12a3 45" } });
    expect((input as HTMLInputElement).value).toBe("12345");

    fireEvent.click(screen.getByText("Добавить в бот"));

    await waitFor(() => expect(addMock).toHaveBeenCalledTimes(1));
    expect(addMock).toHaveBeenCalledWith({
      telegram_id: 12345,
      display_name: undefined,
      department_id: undefined,
      position: undefined,
    });
    await waitFor(() => expect(onAdded).toHaveBeenCalledTimes(1));
    expect(alertMock).toHaveBeenCalledWith("Аня заведён(а) в боте.");
  });

  it("не даёт отправить короткий ID", () => {
    renderPanel(<AddPersonPanel onAdded={() => {}} />);
    fireEvent.click(screen.getByText("Добавить по Telegram ID"));
    fireEvent.change(screen.getByPlaceholderText("например, 123456789"), {
      target: { value: "12" },
    });
    const button = screen.getByText("Добавить в бот") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});

describe("RosterSnapshotsPanel", () => {
  it("восстанавливает выбранный снимок и показывает разбивку", async () => {
    snapshotsMock.mockResolvedValue({
      max_snapshots: 20,
      items: [
        {
          id: 7,
          label: "Перед чисткой",
          kind: "manual",
          source: "employees",
          people_count: 12,
          created_at: "2026-10-20T10:00:00Z",
        },
      ],
    });
    restoreMock.mockResolvedValue({
      created: 2,
      restored: 1,
      skipped: 9,
      departments_missing: [],
    });
    renderPanel(<RosterSnapshotsPanel />);

    fireEvent.click(screen.getByText("Снапшоты состава"));
    expect(await screen.findByText("Перед чисткой")).toBeTruthy();
    expect(screen.getByText("12 чел.")).toBeTruthy();

    fireEvent.click(screen.getByText("Восстановить"));
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(restoreMock).toHaveBeenCalledWith(7));
    await waitFor(() =>
      expect(alertMock).toHaveBeenCalledWith(
        "Заведено заново: 2\nВозвращено из корзины: 1\nНе тронуто (уже есть): 9",
      ),
    );
  });

  it("снимает снимок кнопкой и сообщает размер состава", async () => {
    snapshotsMock.mockResolvedValue({ max_snapshots: 20, items: [] });
    createMock.mockResolvedValue({
      snapshot: {
        id: 8,
        label: "Снимок",
        kind: "manual",
        source: "employees",
        people_count: 15,
        created_at: "2026-10-20T10:00:00Z",
      },
      people: [],
    });
    renderPanel(<RosterSnapshotsPanel />);

    fireEvent.click(screen.getByText("Снапшоты состава"));
    fireEvent.click(screen.getByText("Снять снапшот сейчас"));

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(alertMock).toHaveBeenCalledWith(
        "Снимок готов: людей в составе — 15.",
      ),
    );
  });
});
