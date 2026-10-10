// @vitest-environment jsdom
/**
 * GHG11(14): строка верхнего топа по рейтингу.
 *
 * Проверяем, что звание видно и на телефоне: ранг раньше стоял только в
 * «широкой» разметке (`hidden sm:block`) и на узком экране пропадал целиком.
 * Теперь он живёт и во второй строке плашкой — при этом уровень, XP и процент
 * собранных ачивок остаются на месте.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LeaderboardScreen from "./LeaderboardScreen";
import type { RankRow } from "@/api/game";
import type { User } from "@/types";

vi.mock("@/api/meetings", () => ({
  fetchLoserStats: vi.fn(),
}));
vi.mock("@/api/admin", () => ({
  fetchChukhanLeaderboard: vi.fn(),
}));
vi.mock("@/api/game", () => ({
  fetchRanksChart: vi.fn(),
}));

import { fetchLoserStats } from "@/api/meetings";
import { fetchChukhanLeaderboard } from "@/api/admin";
import { fetchRanksChart } from "@/api/game";

afterEach(cleanup);

const USERS: User[] = [
  {
    id: 1,
    telegram_id: 111,
    display_name: "Кравченко",
    username: null,
    avatar_url: null,
    color_hex: "#ec4899",
    timezone: "Europe/Moscow",
    created_at: "2026-01-01T00:00:00Z",
  },
];

const ROW: RankRow = {
  user_id: 1,
  xp: 420,
  level: 7,
  rank_name: "Воин кринжа",
  hex: "#ec4899",
  bold: false,
  supreme: false,
  achievements_percent: 62,
  achievements_collected: 5,
  achievements_total: 8,
};

function mount() {
  vi.mocked(fetchLoserStats).mockResolvedValue({
    counts: {},
    last: null,
    cooldown_remaining_seconds: 0,
  });
  vi.mocked(fetchChukhanLeaderboard).mockResolvedValue([]);
  vi.mocked(fetchRanksChart).mockResolvedValue([ROW]);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LeaderboardScreen users={USERS} />
    </QueryClientProvider>,
  );
}

describe("LeaderboardScreen: топ по рейтингу (GHG11(14))", () => {
  it("строка несёт ранга, уровень, XP и процент ачивок разом", async () => {
    mount();
    const row = await screen.findByText("Кравченко");
    const li = row.closest("li");
    expect(li).not.toBeNull();
    const text = li!.textContent ?? "";
    expect(text).toContain("Воин кринжа");
    expect(text).toContain("Ур. 7");
    expect(text).toContain("420 XP");
    expect(text).toContain("62%");
  });

  it("плашка ранга есть и в мобильной строке (не только в широкой)", async () => {
    mount();
    await screen.findByText("Кравченко");
    // Две плашки: компактная в мета-строке и обычная справа (расширенный экран).
    const plaques = screen.getAllByText("Воин кринжа");
    expect(plaques).toHaveLength(2);
    expect(plaques.some((p) => p.closest(".sm\\:hidden"))).toBe(true);
  });
});
