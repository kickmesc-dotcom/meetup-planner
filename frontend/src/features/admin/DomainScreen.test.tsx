// @vitest-environment jsdom
/**
 * Свой домен (06.11.2026).
 *
 * Проверяем обещания, ради которых экран существует: владелец видит, работает
 * ли домен, инструкция берётся из ответа сервера (а не из головы), сохранение
 * и проверка зовут свои ручки.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DomainScreen from "./DomainScreen";
import {
  clearOrgDomain,
  fetchOrgDomain,
  saveOrgDomain,
  verifyOrgDomain,
  type OrgDomain,
} from "@/api/orgs";

vi.mock("@/api/orgs", () => ({
  fetchOrgDomain: vi.fn(),
  saveOrgDomain: vi.fn(),
  verifyOrgDomain: vi.fn(),
  clearOrgDomain: vi.fn(),
}));
// Оболочка — не предмет теста: у неё свои кнопки и haptic.
vi.mock("./SubScreen", () => ({
  default: ({
    title,
    subtitle,
    children,
  }: {
    title: string;
    subtitle?: string;
    children: React.ReactNode;
  }) => (
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
      {children}
    </div>
  ),
}));

const fetchMock = vi.mocked(fetchOrgDomain);
const saveMock = vi.mocked(saveOrgDomain);
const verifyMock = vi.mocked(verifyOrgDomain);
const clearMock = vi.mocked(clearOrgDomain);

function row(overrides: Partial<OrgDomain> = {}): OrgDomain {
  return {
    domain: "cabinet.salon.ru",
    token: "abc123",
    verified: false,
    checked_at: null,
    verify_path: "/.well-known/semitask-domain.txt",
    verify_prefix: "semitask-domain=",
    ...overrides,
  };
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DomainScreen onBack={() => undefined} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  saveMock.mockReset();
  verifyMock.mockReset();
  clearMock.mockReset();
  fetchMock.mockResolvedValue(row());
  saveMock.mockResolvedValue(row({ domain: "new.salon.ru", verified: false }));
  verifyMock.mockResolvedValue(row({ verified: true }));
  clearMock.mockResolvedValue(row({ domain: null, token: null, verified: false }));
});
afterEach(cleanup);

describe("DomainScreen", () => {
  it("показывает домен, статус и инструкцию из ответа сервера", async () => {
    renderScreen();

    await screen.findByDisplayValue("cabinet.salon.ru");
    expect(
      screen.getByText("Ждёт подтверждения: пока работает платформенная ссылка."),
    ).toBeTruthy();
    expect(screen.getByText("semitask-domain=abc123")).toBeTruthy();
    expect(
      screen.getByText("https://cabinet.salon.ru/.well-known/semitask-domain.txt"),
    ).toBeTruthy();
  });

  it("сохраняет новое имя домена", async () => {
    renderScreen();

    // Подпись теперь с маркером обязательности: ищем по части текста.
    const input = await screen.findByLabelText(/Домен/);
    fireEvent.change(input, { target: { value: "new.salon.ru" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(saveMock).toHaveBeenCalledWith("new.salon.ru"));
  });

  it("запускает проверку контроля", async () => {
    renderScreen();

    await screen.findByDisplayValue("cabinet.salon.ru");
    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));

    await waitFor(() => expect(verifyMock).toHaveBeenCalled());
  });

  it("без домена показывает платформенную ссылку как рабочую", async () => {
    fetchMock.mockResolvedValue(row({ domain: null, token: null }));
    renderScreen();

    expect(await screen.findByText("Домен не задан")).toBeTruthy();
    expect(
      screen.getByText("Работает платформенная ссылка — свой домен её дополнит."),
    ).toBeTruthy();
  });
});
