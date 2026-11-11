// @vitest-environment jsdom
/**
 * Админка платформы (шаг 4.3).
 *
 * Проверяем решения, а не разметку:
 *  - тариф меняется тем кодом, который выбрал человек, и уходит на сервер;
 *  - блокировка — это переключатель `is_active`, а не удаление клиента;
 *  - «подтвердить оплату» вызывает отдельную ручку: именно она продлевает
 *    подписку, поэтому кнопка не должна быть декоративной.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PlatformScreen from "./PlatformScreen";
import {
  cancelPlatformInvoice,
  confirmPlatformInvoice,
  fetchPlatformInvoices,
  fetchPlatformOnboarding,
  fetchPlatformOrgs,
  fetchPlatformRum,
  fetchPlatformSummary,
  patchPlatformOrg,
  type PlatformSummary,
} from "@/api/platform";

vi.mock("@/api/platform", () => ({
  fetchPlatformSummary: vi.fn(),
  fetchPlatformRum: vi.fn(),
  fetchPlatformOrgs: vi.fn(),
  fetchPlatformInvoices: vi.fn(),
  fetchPlatformOnboarding: vi.fn(),
  patchPlatformOrg: vi.fn(),
  confirmPlatformInvoice: vi.fn(),
  cancelPlatformInvoice: vi.fn(),
}));

const summaryMock = vi.mocked(fetchPlatformSummary);
const rumMock = vi.mocked(fetchPlatformRum);
const orgsMock = vi.mocked(fetchPlatformOrgs);
const invoicesMock = vi.mocked(fetchPlatformInvoices);
const onboardingMock = vi.mocked(fetchPlatformOnboarding);
const patchMock = vi.mocked(patchPlatformOrg);
const confirmMock = vi.mocked(confirmPlatformInvoice);
const cancelMock = vi.mocked(cancelPlatformInvoice);

const SUMMARY: PlatformSummary = {
  organizations: 2,
  active: 1,
  on_trial: 1,
  expired: 1,
  awaiting_invoices: 1,
  unpaid_amount: 7900,
  plans: [
    { code: "trial", title: "Пробный", seats: 10, branches: 5, price_month: 0, price_year: 0 },
    { code: "business", title: "Бизнес", seats: 50, branches: 15, price_month: 7900, price_year: 79000 },
  ],
};

const ORG = {
  id: 3,
  slug: "salon-a",
  name: "Салон А",
  industry: "salon",
  is_active: true,
  plan: "trial",
  plan_title: "Пробный",
  seats_used: 2,
  seats_limit: 10,
  branches_used: 1,
  branches_limit: 5,
  trial_ends_at: "2026-11-16T00:00:00+00:00",
  plan_ends_at: null,
  trial_expired: false,
  subscription_expired: false,
  created_at: "2026-11-01T00:00:00+00:00",
};

const INVOICE = {
  id: 9,
  org_id: 3,
  org_name: "Салон А",
  number: "INV-20261103-ABC123",
  plan: "business",
  plan_title: "Бизнес",
  period: "month",
  amount: 7900,
  currency: "RUB",
  status: "awaiting",
  created_at: "2026-11-03T10:00:00+00:00",
  expires_at: "2026-11-10T10:00:00+00:00",
  paid_at: null,
  period_start: null,
  period_end: null,
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PlatformScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  summaryMock.mockReset();
  orgsMock.mockReset();
  invoicesMock.mockReset();
  patchMock.mockReset();
  confirmMock.mockReset();
  cancelMock.mockReset();
  summaryMock.mockResolvedValue(SUMMARY);
  rumMock.mockResolvedValue({
    window_seconds: 86_400,
    events: 0,
    metrics: {},
    top_paths: [],
    builds: [],
  });
  orgsMock.mockResolvedValue({ items: [ORG], total: 1 });
  invoicesMock.mockResolvedValue({ items: [INVOICE], total: 1, awaiting: 1 });
  onboardingMock.mockResolvedValue({
    orgs: [
      {
        org_id: 3,
        name: "Салон А",
        people: 4,
        first_task_done: 3,
        first_task_share: 0.75,
        median_hours_to_first_task: 5.5,
        first_checklist_done: 2,
        first_checklist_share: 0.5,
        median_hours_to_first_checklist: 9,
        onboarding_done: 1,
        onboarding_share: 0.25,
      },
    ],
    totals: {
      people: 4,
      first_task_done: 3,
      first_task_share: 0.75,
      median_hours_to_first_task: 5.5,
      first_checklist_done: 2,
      first_checklist_share: 0.5,
      median_hours_to_first_checklist: 9,
      onboarding_done: 1,
      onboarding_share: 0.25,
    },
  });
  patchMock.mockResolvedValue({ ...ORG, plan: "business" });
  confirmMock.mockResolvedValue({ ...INVOICE, status: "paid" });
  cancelMock.mockResolvedValue({ ...INVOICE, status: "canceled" });
});

describe("PlatformScreen", () => {
  it("показывает сводку и количество ожидающих оплату", async () => {
    renderScreen();

    // Название есть и в карточке клиента, и в счёте: берём карточку.
    expect(await screen.findByTestId("org-3")).toBeTruthy();
    expect(screen.getByText("Организаций")).toBeTruthy();
    // Сумма есть и в сводке, и в счёте: важно, что она пришла с сервера.
    expect(screen.getAllByText("7 900 ₽").length).toBeGreaterThan(0);
  });

  it("меняет тариф тем кодом, который выбрал человек", async () => {
    renderScreen();

    const select = (await screen.findByLabelText("Тариф")) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "business" } });

    await vi.waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith(3, { plan: "business" }),
    );
  });

  it("блокирует клиента переключателем is_active", async () => {
    renderScreen();

    fireEvent.click(await screen.findByText("Заблокировать"));

    await vi.waitFor(() =>
      expect(patchMock).toHaveBeenCalledWith(3, { is_active: false }),
    );
  });

  it("показывает онбординг: долю дошедших и медиану до первой задачи", async () => {
    renderScreen();

    const card = await screen.findByTestId("platform-onboarding");
    // Итог — 75 % и 5,5 ч: это цифры с сервера, а не «0 %» по умолчанию.
    expect(card.textContent).toContain("75%");
    expect(card.textContent).toContain("5.5 ч");
    // Отстающая организация видна в списке, иначе карточка не помогает
    // понять, кому звонить.
    expect(card.textContent).toContain("Салон А");
  });

  it("подтверждает оплату отдельной ручкой", async () => {
    renderScreen();

    fireEvent.click(await screen.findByText("Подтвердить оплату"));

    await vi.waitFor(() => expect(confirmMock).toHaveBeenCalledWith(9));
  });
});
