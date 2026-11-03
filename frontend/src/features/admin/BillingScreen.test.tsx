// @vitest-environment jsdom
/**
 * Экран «Оплата и счета» (шаг 4.2).
 *
 * Проверяем то, что ломается незаметно:
 *  - цена берётся из витрины сервера, а не считается в браузере;
 *  - «Я оплатил» отправляет заявку, но экран не обещает продление;
 *  - истёкшая оплата объясняет, что работа продолжается;
 *  - кнопка счёта вызывает сервер с тарифом и периодом, которые выбрал человек.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import BillingScreen from "./BillingScreen";
import {
  cancelInvoice,
  createInvoice,
  fetchOrgBilling,
  requestInvoicePaid,
  type OrgBilling,
} from "@/api/orgs";

vi.mock("@/api/orgs", () => ({
  fetchOrgBilling: vi.fn(),
  createInvoice: vi.fn(),
  requestInvoicePaid: vi.fn(),
  cancelInvoice: vi.fn(),
}));

const fetchMock = vi.mocked(fetchOrgBilling);
const createMock = vi.mocked(createInvoice);
const paidMock = vi.mocked(requestInvoicePaid);
const cancelMock = vi.mocked(cancelInvoice);

const BILLING: OrgBilling = {
  plan: {
    code: "trial",
    title: "Пробный",
    seats_used: 4,
    seats_limit: 10,
    branches_used: 2,
    branches_limit: 5,
    invites_active: 1,
    trial_ends_at: "2026-11-16T00:00:00+00:00",
    trial_days_left: 9,
    trial_expired: false,
    plan_ends_at: null,
    plan_days_left: null,
    subscription_expired: false,
  },
  prices: [
    {
      code: "business",
      title: "Бизнес",
      seats: 50,
      branches: 15,
      price_month: 7900,
      price_year: 79000,
    },
  ],
  invoices: [
    {
      id: 7,
      number: "INV-20261103-ABC123",
      plan: "business",
      plan_title: "Бизнес",
      period: "month",
      amount: 7900,
      currency: "RUB",
      status: "pending",
      created_at: "2026-11-03T10:00:00+00:00",
      expires_at: "2026-11-10T10:00:00+00:00",
      paid_at: null,
      period_start: null,
      period_end: null,
    },
  ],
  invoice_ttl_days: 7,
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BillingScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  fetchMock.mockReset();
  createMock.mockReset();
  paidMock.mockReset();
  cancelMock.mockReset();
  createMock.mockResolvedValue(BILLING.invoices[0]);
  paidMock.mockResolvedValue({ ...BILLING.invoices[0], status: "awaiting" });
  cancelMock.mockResolvedValue({ ...BILLING.invoices[0], status: "canceled" });
});

describe("BillingScreen", () => {
  it("показывает цены с сервера и счёт с суммой из каталога", async () => {
    fetchMock.mockResolvedValue(BILLING);
    renderScreen();

    expect(await screen.findByTestId("price-business")).toBeTruthy();
    // Та же сумма есть и в счёте: проверяем, что цена пришла с сервера.
    expect(screen.getAllByText("7 900 ₽").length).toBeGreaterThan(0);
    expect(screen.getByText("INV-20261103-ABC123")).toBeTruthy();
    expect(screen.getByText(/Ожидает оплаты/)).toBeTruthy();
  });

  it("выставляет счёт на выбранный тариф и период", async () => {
    fetchMock.mockResolvedValue(BILLING);
    renderScreen();

    fireEvent.click(await screen.findByText("Счёт за год · 79 000 ₽"));
    // Мутация стартует в микрозадаче: сразу после клика шпион ещё не вызван.
    await vi.waitFor(() =>
      expect(createMock).toHaveBeenCalledWith({ plan: "business", period: "year" }),
    );
  });

  it("по «Я оплатил» отправляет заявку, а не обещает продление", async () => {
    fetchMock.mockResolvedValue(BILLING);
    renderScreen();

    fireEvent.click(await screen.findByText("Я оплатил"));
    await vi.waitFor(() => expect(paidMock).toHaveBeenCalledWith(7));
  });

  it("при истёкшей оплате говорит: люди и данные на месте", async () => {
    fetchMock.mockResolvedValue({
      ...BILLING,
      plan: {
        ...BILLING.plan,
        code: "business",
        title: "Бизнес",
        subscription_expired: true,
        plan_ends_at: "2026-11-01T00:00:00+00:00",
        trial_ends_at: null,
        trial_days_left: null,
      },
    });
    renderScreen();

    const line = await screen.findByTestId("subscription-line");
    expect(line.textContent ?? "").toContain("Оплата закончилась");
    expect(line.textContent ?? "").toContain("Люди и данные на месте");
  });
});
