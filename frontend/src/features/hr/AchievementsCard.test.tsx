// @vitest-environment jsdom
/**
 * SemiTaskBot: карточка «личный прогресс».
 *
 * Проверяем ровно то, что решил владелец: блок скрыт, пока сервер не разрешил
 * его показывать, и показывает выданные ачивки с целями, когда разрешил. Никакой
 * клиентской логики видимости тут нет — только реакция на `visible`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AchievementsCard from "./AchievementsCard";
import * as hrApi from "@/api/hr";

function renderCard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AchievementsCard />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AchievementsCard", () => {
  it("не рисует ничего, пока блок скрыт", async () => {
    vi.spyOn(hrApi, "fetchAchievements").mockResolvedValue({
      visible: false,
      awarded: [],
      stats: {},
      next_goals: [],
      note: "скрыто",
    });
    const { container } = renderCard();
    await waitFor(() => expect(hrApi.fetchAchievements).toHaveBeenCalled());
    expect(container.textContent).not.toContain("Личный прогресс");
  });

  it("показывает ачивки, счётчики и ближайшие цели", async () => {
    vi.spyOn(hrApi, "fetchAchievements").mockResolvedValue({
      visible: true,
      awarded: [
        {
          code: "first_task",
          title: "Первое закрытое поручение",
          emoji: "🎯",
          awarded_at: "2026-10-16T10:00:00Z",
        },
      ],
      stats: { tasks_done: 1, shift_days: 0, checklist_items: 0 },
      next_goals: [
        {
          code: "tasks_10",
          title: "10 закрытых поручений",
          emoji: "🔟",
          metric: "tasks_done",
          threshold: 10,
          done: 1,
          left: 9,
          text: "10 закрытых поручений: 1/10 (осталось 9)",
        },
      ],
      note: "",
    });
    renderCard();
    expect(await screen.findByText(/Личный прогресс/)).toBeTruthy();
    expect(screen.getByText(/Первое закрытое поручение/)).toBeTruthy();
    expect(screen.getByText(/осталось 9|1\/10/)).toBeTruthy();
  });
});
