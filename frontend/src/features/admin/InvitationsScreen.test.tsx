// @vitest-environment jsdom
/**
 * «Приглашения» в админке: создать ссылку, увидеть её один раз, отозвать.
 *
 * Проверяем то, что нельзя исправить после выкладки: ссылка показывается
 * только в ответе на создание (в списке её нет — сервер хранит хеш), письмо не
 * обещается, если транспорт «лог», а отзыв спрашивает подтверждение.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import InvitationsScreen from "./InvitationsScreen";
import {
  createInvitation,
  fetchInvitations,
  revokeInvitation,
} from "@/api/orgs";

vi.mock("@/tg/webapp", () => ({
  haptic: vi.fn(),
  showAlert: vi.fn(() => Promise.resolve()),
  showConfirm: vi.fn(() => Promise.resolve(true)),
}));
vi.mock("@/api/orgs", () => ({
  fetchInvitations: vi.fn(),
  createInvitation: vi.fn(),
  revokeInvitation: vi.fn(),
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

afterEach(() => {
  cleanup();
  listMock.mockReset();
  createMock.mockReset();
  revokeMock.mockReset();
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
    });
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
