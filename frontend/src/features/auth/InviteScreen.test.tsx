// @vitest-environment jsdom
/**
 * Экран `/invite`: кто зовёт, какая роль и что делать, если что-то не так.
 *
 * Главные обещания:
 *  • до принятия человек видит организацию и роль, а не пустую форму;
 *  • после принятия экран говорит «ты в организации» и ведёт в приложение;
 *  • именное приглашение под чужой почтой объясняется и предлагает сменить
 *    аккаунт, а не оставляет тупик;
 *  • протухшая ссылка — человеческий текст, а не HTTP-код.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import InviteScreen from "./InviteScreen";
import { acceptInvitation, previewInvitation } from "@/api/orgs";
import { ApiError } from "@/api/client";

vi.mock("@/tg/webapp", () => ({
  getInitData: vi.fn(() => ""),
  haptic: vi.fn(),
}));
vi.mock("@/api/auth", () => ({
  logoutRequest: vi.fn(() => Promise.resolve({ ok: true })),
}));
vi.mock("@/api/orgs", () => ({
  previewInvitation: vi.fn(),
  acceptInvitation: vi.fn(),
  ORG_ROLE_LABELS: {
    owner: "Владелец",
    manager: "Управляющий",
    staff: "Сотрудник",
  },
}));

const previewMock = vi.mocked(previewInvitation);
const acceptMock = vi.mocked(acceptInvitation);

function renderScreen() {
  const onDone = vi.fn();
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <InviteScreen token="invite_tok" onDone={onDone} />
    </QueryClientProvider>,
  );
  return onDone;
}

afterEach(() => {
  cleanup();
  previewMock.mockReset();
  acceptMock.mockReset();
});

describe("InviteScreen", () => {
  it("показывает организацию, роль и срок", async () => {
    previewMock.mockResolvedValue({
      org_name: "Салон «Красота»",
      role: "manager",
      email: null,
      expires_at: "2026-11-01T12:00:00+00:00",
    });
    renderScreen();

    expect(await screen.findByText("Салон «Красота»")).toBeTruthy();
    expect(screen.getByText(/Управляющий/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Присоединиться" })).toBeTruthy();
  });

  it("после принятия ведёт в приложение", async () => {
    previewMock.mockResolvedValue({
      org_name: "Салон «Красота»",
      role: "staff",
      email: null,
      expires_at: "2026-11-01T12:00:00+00:00",
    });
    acceptMock.mockResolvedValue({
      ok: true,
      org_id: 2,
      org_name: "Салон «Красота»",
      role: "staff",
    });
    const onDone = renderScreen();

    fireEvent.click(
      await screen.findByRole("button", { name: "Присоединиться" }),
    );

    expect(await screen.findByText("Ты в организации")).toBeTruthy();
    expect(acceptMock).toHaveBeenCalledWith("invite_tok");
    expect(onDone).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Открыть приложение" }));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("именное приглашение под чужой почтой предлагает сменить аккаунт", async () => {
    previewMock.mockResolvedValue({
      org_name: "Салон",
      role: "staff",
      email: "invited@example.com",
      expires_at: "2026-11-01T12:00:00+00:00",
    });
    acceptMock.mockRejectedValue(new ApiError(403, "invite_email_mismatch"));
    renderScreen();

    expect(
      await screen.findByText(/Приглашение выписано на invited@example.com/),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Присоединиться" }));

    expect(await screen.findByText(/выписано на другую почту/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Войти под другой почтой" }),
    ).toBeTruthy();
  });

  it("протухшая ссылка объясняется по-русски", async () => {
    previewMock.mockRejectedValue(new ApiError(410, "invite_expired"));
    const onDone = renderScreen();

    expect(
      await screen.findByText("Срок приглашения истёк — попроси новую ссылку."),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Перейти в приложение" }));
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
