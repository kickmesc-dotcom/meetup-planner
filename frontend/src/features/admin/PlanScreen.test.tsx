// @vitest-environment jsdom
/**
 * Экран «Тариф и лимиты» (шаг 4.1).
 *
 * Проверяем то, что ломается незаметно:
 *  - занятые места показываются вместе с приглашениями (иначе руководитель
 *    выписывает ссылки и не понимает, почему десятая не создалась);
 *  - истёкший триал объясняет, что работа продолжается, а не пугает «блокировкой»;
 *  - кнопка ведёт туда, где лимит можно потратить, — в приглашения.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PlanScreen from "./PlanScreen";
import { fetchOrgPlan, type OrgPlan } from "@/api/orgs";
import { useUI } from "@/store/ui";

vi.mock("@/api/orgs", () => ({
  fetchOrgPlan: vi.fn(),
}));

const fetchMock = vi.mocked(fetchOrgPlan);

const PLAN: OrgPlan = {
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
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PlanScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  fetchMock.mockReset();
  useUI.setState({ adminSection: "root" });
});

describe("PlanScreen", () => {
  it("показывает тариф, занятые места и остаток триала", async () => {
    fetchMock.mockResolvedValue(PLAN);
    renderScreen();

    expect(await screen.findByText("Пробный")).toBeTruthy();
    expect(screen.getByText("4 из 10")).toBeTruthy();
    expect(screen.getByText("2 из 5")).toBeTruthy();
    expect(screen.getByText("Осталось 9 дн.")).toBeTruthy();
  });

  it("после триала честно говорит: работа продолжается, рост закрыт", async () => {
    fetchMock.mockResolvedValue({
      ...PLAN,
      trial_expired: true,
      trial_days_left: null,
    });
    renderScreen();

    const banner = await screen.findByTestId("trial-expired");
    expect(banner.textContent ?? "").toContain("Люди и данные на месте");
    expect(screen.queryByText(/Осталось/)).toBeNull();
  });

  it("ведёт приглашать туда, где лимит тратится", async () => {
    fetchMock.mockResolvedValue({ ...PLAN, seats_used: 10 });
    renderScreen();

    fireEvent.click(await screen.findByText("Пригласить человека"));
    expect(useUI.getState().adminSection).toBe("invitations");
  });
});
