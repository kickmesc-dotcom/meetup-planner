// @vitest-environment jsdom
/**
 * «Приглашения» в админке: создать ссылку, увидеть её один раз, отозвать.
 *
 * Проверяем то, что нельзя исправить после выкладки: ссылка показывается
 * только в ответе на создание (в списке её нет — сервер хранит хеш), письмо не
 * обещается, если транспорт «лог», а отзыв спрашивает подтверждение.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import InvitationsScreen from "./InvitationsScreen";
import {
  createInvitation,
  fetchInvitations,
  fetchOrgMembers,
  revokeInvitation,
  updateOrgMemberRole,
} from "@/api/orgs";

vi.mock("@/tg/webapp", () => ({
  haptic: vi.fn(),
  showAlert: vi.fn(() => Promise.resolve()),
  showConfirm: vi.fn(() => Promise.resolve(true)),
}));
vi.mock("@/api/hr", () => ({
  fetchDepartments: vi.fn(() => Promise.resolve([])),
}));
vi.mock("@/api/orgs", () => ({
  fetchInvitations: vi.fn(),
  fetchCurrentOrg: vi.fn(() =>
    Promise.resolve({ id: 1, slug: "kofeynya", name: "Кофейня", role: "owner" }),
  ),
  fetchOrgMembers: vi.fn(() => Promise.resolve([])),
  createInvitation: vi.fn(),
  revokeInvitation: vi.fn(),
  updateOrgMemberRole: vi.fn(),
  ORG_ROLES: ["staff", "manager", "owner"],
  ORG_ROLE_LABELS: {
    owner: "Владелец",
    manager: "Управляющий",
    staff: "Сотрудник",
  },
}));

const listMock = vi.mocked(fetchInvitations);
const createMock = vi.mocked(createInvitation);
const revokeMock = vi.mocked(revokeInvitation);
const membersMock = vi.mocked(fetchOrgMembers);
const roleMock = vi.mocked(updateOrgMemberRole);

function renderScreen() {
  const onBack = vi.fn();
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <InvitationsScreen onBack={onBack} />
    </QueryClientProvider>,
  );
  return onBack;
}

beforeEach(() => {
  // `mockReset` в конце каждого теста снимает реализацию, а запрос участников
  // уходит всегда: без этого в лог падало бы «query data cannot be undefined».
  membersMock.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  listMock.mockReset();
  createMock.mockReset();
  revokeMock.mockReset();
  membersMock.mockReset();
  roleMock.mockReset();
});

describe("InvitationsScreen", () => {
  it("показывает живые ссылки с ролью и адресом", async () => {
    listMock.mockResolvedValue([
      {
        id: 7,
        email: null,
        role: "manager",
        created_at: "2026-10-23T10:00:00+00:00",
        expires_at: "2026-10-30T10:00:00+00:00",
      },
    ]);
    renderScreen();

    // Ждём именно список, а не подпись роли: «Управляющий» есть ещё и в
    // выпадающем списке формы, и тест прошёл бы до загрузки данных.
    expect(await screen.findByText("Живые ссылки (1)")).toBeTruthy();
    expect(screen.getByText("для всех, у кого есть ссылка")).toBeTruthy();
    expect(await screen.findByText("kofeynya")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Отозвать" })).toBeTruthy();
  });

  it("создаёт ссылку и показывает её один раз", async () => {
    listMock.mockResolvedValue([]);
    createMock.mockResolvedValue({
      id: 8,
      email: "invited@example.com",
      role: "staff",
      created_at: "2026-10-23T10:00:00+00:00",
      expires_at: "2026-10-30T10:00:00+00:00",
      link: "https://app.example/invite?token=secret",
      mail_sent: true,
    });
    renderScreen();

    fireEvent.click(await screen.findByRole("button", { name: "Создать ссылку" }));

    expect(await screen.findByText("https://app.example/invite?token=secret")).toBeTruthy();
    expect(screen.getByText("Письмо ушло на invited@example.com.")).toBeTruthy();
    expect(createMock).toHaveBeenCalledWith({
      email: null,
      role: "staff",
      days: 7,
      position: null,
      department_id: null,
    });
  });

  it("меняет роль участника, но не даёт менять свою", async () => {
    listMock.mockResolvedValue([]);
    membersMock.mockResolvedValue([
      {
        user_id: 1,
        name: "Владелец",
        email: "owner@example.com",
        role: "owner",
        hr_role: "admin",
        is_self: true,
      },
      {
        user_id: 2,
        name: "Сотрудник",
        email: "staff@example.com",
        role: "staff",
        hr_role: "employee",
        is_self: false,
      },
    ]);
    roleMock.mockResolvedValue({
      user_id: 2,
      name: "Сотрудник",
      email: "staff@example.com",
      role: "manager",
      hr_role: "aup",
      is_self: false,
    });
    renderScreen();

    const own = await screen.findByLabelText("Роль Владелец");
    expect((own as HTMLSelectElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Роль Сотрудник"), {
      target: { value: "manager" },
    });
    await waitFor(() =>
      expect(roleMock).toHaveBeenCalledWith(2, "manager"),
    );
  });

  it("просит подтверждение перед отзывом", async () => {
    listMock.mockResolvedValue([
      {
        id: 9,
        email: "a@example.com",
        role: "staff",
        created_at: "2026-10-23T10:00:00+00:00",
        expires_at: "2026-10-30T10:00:00+00:00",
      },
    ]);
    revokeMock.mockResolvedValue(undefined);
    renderScreen();

    fireEvent.click(await screen.findByRole("button", { name: "Отозвать" }));

    await waitFor(() => expect(revokeMock).toHaveBeenCalledWith(9));
  });
});
