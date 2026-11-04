// @vitest-environment jsdom
/**
 * Экран «Интеграции» (шаг 6.1).
 *
 * Проверяем то, что ломается незаметно:
 *  - ключ показывается один раз и именно после создания;
 *  - отзыв требует подтверждения, а не срабатывает от одного нажатия;
 *  - адрес вебхука не принимается пустым (курсор в поле — не повод слать 400);
 *  - журнал доставок читается как «что мы отправили».
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import IntegrationsScreen from "./IntegrationsScreen";
import {
  createApiKey,
  createWebhook,
  fetchApiKeys,
  fetchDeliveries,
  fetchWebhooks,
  revokeApiKey,
} from "@/api/integrations";

vi.mock("@/api/integrations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/integrations")>();
  return {
    ...actual,
    fetchApiKeys: vi.fn(),
    createApiKey: vi.fn(),
    revokeApiKey: vi.fn(),
    fetchWebhooks: vi.fn(),
    createWebhook: vi.fn(),
    updateWebhook: vi.fn(),
    deleteWebhook: vi.fn(),
    fetchDeliveries: vi.fn(),
  };
});

const keysMock = vi.mocked(fetchApiKeys);
const createKeyMock = vi.mocked(createApiKey);
const revokeMock = vi.mocked(revokeApiKey);
const hooksMock = vi.mocked(fetchWebhooks);
const createHookMock = vi.mocked(createWebhook);
const deliveriesMock = vi.mocked(fetchDeliveries);

const KEY = {
  id: 1,
  name: "CRM",
  prefix: "stk_live_7fa2",
  scopes: ["people.read", "schedule.read"],
  created_at: "2026-11-04T10:00:00+00:00",
  last_used_at: null,
  revoked_at: null,
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <IntegrationsScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  keysMock.mockResolvedValue([KEY]);
  hooksMock.mockResolvedValue([]);
  deliveriesMock.mockResolvedValue([
    {
      id: 7,
      endpoint_id: 3,
      event: "employee.created",
      status: "sent",
      attempts: 1,
      response_code: 200,
      error: null,
      created_at: "2026-11-04T10:05:00+00:00",
      delivered_at: "2026-11-04T10:05:01+00:00",
    },
  ]);
  createKeyMock.mockResolvedValue({
    key: { ...KEY, id: 2, name: "Учёт" },
    token: "stk_live_supersecretvalue",
  });
  createHookMock.mockResolvedValue({
    webhook: {
      id: 3,
      url: "https://crm.example.com/hook",
      events: ["employee.created"],
      is_active: true,
      created_at: "2026-11-04T10:00:00+00:00",
      last_attempt_at: null,
      last_status_code: null,
      failures: 0,
    },
    secret: "whsec_abc",
  });
  revokeMock.mockResolvedValue({ ...KEY, revoked_at: "2026-11-04T11:00:00+00:00" });
});

describe("IntegrationsScreen", () => {
  it("создаёт ключ и показывает токен один раз", async () => {
    renderScreen();
    await screen.findByText("CRM");

    fireEvent.change(screen.getByPlaceholderText("Например: CRM"), {
      target: { value: "Учёт" },
    });
    fireEvent.click(screen.getByText("Создать ключ"));

    await waitFor(() => expect(createKeyMock).toHaveBeenCalled());
    expect(createKeyMock.mock.calls[0][0]).toBe("Учёт");
    expect(await screen.findByText("stk_live_supersecretvalue")).toBeTruthy();
  });

  it("отзывает ключ только после подтверждения", async () => {
    renderScreen();
    await screen.findByText("CRM");

    fireEvent.click(screen.getByText("Отозвать"));
    expect(revokeMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Да, отозвать"));
    await waitFor(() => expect(revokeMock).toHaveBeenCalledWith(1));
  });

  it("не отправляет вебхук с пустым адресом", async () => {
    renderScreen();
    await screen.findByText("Вебхуки");

    const button = screen.getByText("Добавить вебхук") as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText("https://crm.example.com/hooks/semitask"), {
      target: { value: "https://crm.example.com/hook" },
    });
    expect(button.disabled).toBe(false);
  });

  it("показывает журнал доставок, а не только настройки", async () => {
    renderScreen();
    expect(await screen.findByText("Отправлено")).toBeTruthy();
    expect(screen.getByText(/HTTP 200/)).toBeTruthy();
  });
});
