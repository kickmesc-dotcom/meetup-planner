// @vitest-environment jsdom
/**
 * GHG11(7): автообновление ленты.
 *
 * «Как в рилсах»: потянул ленту вниз от верхней кромки и отпустил — данные
 * перезапрашиваются. Проверяем весь путь жест → refetch.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import FeedScreen from "./FeedScreen";
import { fetchFeed } from "@/api/game";
import { fetchMe, fetchUiPrefs, fetchUsers } from "@/api/availability";

vi.mock("@/api/game", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/game")>();
  return {
    ...actual,
    fetchFeed: vi.fn(),
    fetchWorm: vi.fn(),
  };
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

// Панель активностей тянет свои эндпоинты — в этом тесте она не нужна.
vi.mock("./ActivitiesPanel", () => ({ default: () => null }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  vi.mocked(fetchFeed).mockResolvedValue({
    enabled: true,
    items: [],
    next_offset: null,
    kinds: [],
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
  });
  vi.mocked(fetchUsers).mockResolvedValue([]);
});

function renderFeed() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <FeedScreen meId={1} />
    </QueryClientProvider>,
  );
}

describe("FeedScreen: pull-to-refresh (GHG11(7))", () => {
  it("тянем вниз и отпускаем — лента перезапрашивается", async () => {
    renderFeed();
    await screen.findByTestId("feed-scroll");
    await waitFor(() => expect(fetchFeed).toHaveBeenCalledTimes(1));

    const scroller = screen.getByTestId("feed-scroll");
    fireEvent.touchStart(scroller, { touches: [{ clientY: 0 }] });
    fireEvent.touchMove(scroller, { touches: [{ clientY: 200 }] });
    expect(screen.getByTestId("feed-pull-indicator").textContent).toContain(
      "Отпусти",
    );
    fireEvent.touchEnd(scroller);

    await waitFor(() => expect(fetchFeed).toHaveBeenCalledTimes(2));
  });

  it("короткое движение вниз не перезапрашивает ленту", async () => {
    renderFeed();
    await screen.findByTestId("feed-scroll");
    await waitFor(() => expect(fetchFeed).toHaveBeenCalledTimes(1));

    const scroller = screen.getByTestId("feed-scroll");
    fireEvent.touchStart(scroller, { touches: [{ clientY: 0 }] });
    fireEvent.touchMove(scroller, { touches: [{ clientY: 20 }] });
    fireEvent.touchEnd(scroller);

    // Даём шанс отложенному refetch'у, если бы он был.
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchFeed).toHaveBeenCalledTimes(1);
  });
});
