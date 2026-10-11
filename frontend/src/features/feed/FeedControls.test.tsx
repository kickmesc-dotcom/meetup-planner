// @vitest-environment jsdom
/**
 * GHG11(17): блок управления лентой («Все события / Только мои / Фильтры /
 * Действия») сворачивается в одну строку-сводку и разворачивается обратно.
 *
 * Оператор просил именно тумблер: на телефоне строка управления постоянно
 * отбирала высоту у ленты, которую листают чаще, чем меняют фильтры.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import FeedScreen from "./FeedScreen";
import { fetchFeed } from "@/api/game";
import { fetchMe, fetchUiPrefs, fetchUsers } from "@/api/availability";

vi.mock("@/api/game", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/game")>();
  return { ...actual, fetchFeed: vi.fn(), fetchWorm: vi.fn() };
});

vi.mock("@/api/availability", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/availability")>();
  return {
    ...actual,
    fetchMe: vi.fn(),
    fetchUiPrefs: vi.fn(),
    fetchUsers: vi.fn(),
  };
});

beforeEach(() => {
  vi.mocked(fetchFeed).mockResolvedValue({
    enabled: true,
    items: [],
    next_offset: null,
    kinds: ["loser", "music"],
    feed_view: "compact",
  });
  vi.mocked(fetchMe).mockResolvedValue({
    id: 1,
    is_admin: false,
  } as unknown as Awaited<ReturnType<typeof fetchMe>>);
  vi.mocked(fetchUiPrefs).mockResolvedValue({
    hide_greeting: false,
    welcome_format: "avatar",
    muted_feed: [],
    show_last_seen: true,
  });
  vi.mocked(fetchUsers).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderFeed() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <FeedScreen meId={1} />
    </QueryClientProvider>,
  );
}

describe("FeedScreen: сворачиваемый блок управления (GHG11(17))", () => {
  it("по умолчанию развёрнут: видны охват и фильтры", async () => {
    renderFeed();
    await screen.findByTestId("feed-controls");
    expect(screen.getByText("Все события")).toBeTruthy();
    expect(screen.getByText("Только мои")).toBeTruthy();
    expect(screen.getByText("Фильтры")).toBeTruthy();
    expect(screen.getByText("Действия")).toBeTruthy();
    expect(screen.queryByTestId("feed-controls-expand")).toBeNull();
  });

  it("сворачивается в одну строку-сводку и разворачивается обратно", async () => {
    renderFeed();
    await screen.findByTestId("feed-controls");

    fireEvent.click(screen.getByTestId("feed-controls-collapse"));
    // Свёрнуто: осталась одна строка с охватом и подписью состояния.
    expect(screen.queryByText("Фильтры")).toBeNull();
    const expand = screen.getByTestId("feed-controls-expand");
    expect(expand.textContent).toContain("Все события");
    expect(expand.textContent).toContain("все типы");

    fireEvent.click(expand);
    expect(screen.getByText("Фильтры")).toBeTruthy();
    expect(screen.queryByTestId("feed-controls-expand")).toBeNull();
  });

  it("свёрнутая строка честно говорит про выбранный охват", async () => {
    renderFeed();
    await screen.findByTestId("feed-controls");

    fireEvent.click(screen.getByText("Только мои"));
    // Смена охвата — новый запрос ленты: панель перерисуется, когда придут данные.
    const collapse = await screen.findByTestId("feed-controls-collapse");
    fireEvent.click(collapse);
    expect(screen.getByTestId("feed-controls-expand").textContent).toContain(
      "Только мои",
    );
  });
});
