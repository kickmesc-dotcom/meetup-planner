// @vitest-environment jsdom
/**
 * GHG11(9): колокольчик личных уведомлений.
 *
 * Проверяем, что автор трека реально увидит лайк: бейдж с числом непрочитанных,
 * список текстом (тексты собирает сервер), отметку прочитанными при открытии и
 * спокойное пустое состояние (никто ничего не лайкал — ничего и не висит).
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import NotificationsBell, {
  NotificationsList,
  notificationIcon,
  relativeTime,
} from "./NotificationsBell";
import { useUI } from "@/store/ui";
import {
  fetchNotifications,
  readNotifications,
  type NotificationsFeed,
} from "@/api/game";

vi.mock("@/api/game", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/game")>();
  return {
    ...actual,
    fetchNotifications: vi.fn(),
    readNotifications: vi.fn(),
  };
});

const NOW = Date.parse("2026-10-08T12:00:00Z");

const FEED: NotificationsFeed = {
  unread: 2,
  items: [
    {
      id: 2,
      kind: "music_like",
      text: "❤️ Митян лайкнул твой трек «Гимн чата»",
      track_id: 5,
      created_at: "2026-10-08T11:55:00Z",
      read: false,
    },
    {
      id: 1,
      kind: "music_like",
      text: "❤️ Никита лайкнул твой трек «Речь злодея»",
      track_id: 4,
      created_at: "2026-10-07T12:00:00Z",
      read: false,
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  useUI.setState({ feedPanel: false });
  vi.mocked(fetchNotifications).mockResolvedValue(FEED);
  vi.mocked(readNotifications).mockResolvedValue({
    unread: 0,
    items: FEED.items.map((n) => ({ ...n, read: true })),
  });
});

afterEach(cleanup);

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <NotificationsBell />
    </QueryClientProvider>,
  );
}

function mountSheet() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <NotificationsList />
    </QueryClientProvider>,
  );
}

describe("форматирование уведомлений", () => {
  it("relativeTime говорит по-человечески", () => {
    expect(relativeTime("2026-10-08T11:59:30Z", NOW)).toBe("только что");
    expect(relativeTime("2026-10-08T11:30:00Z", NOW)).toBe("30 мин назад");
    expect(relativeTime("2026-10-08T03:00:00Z", NOW)).toBe("9 ч назад");
    expect(relativeTime("2026-10-07T12:00:00Z", NOW)).toBe("вчера");
    expect(relativeTime("2026-10-02T12:00:00Z", NOW)).toBe("6 дн. назад");
    expect(relativeTime(null)).toBe("");
  });

  it("иконка зависит от типа, незнакомый тип не ломает строку", () => {
    expect(notificationIcon("music_like")).toBe("❤️");
    expect(notificationIcon("что-то_новое")).toBe("🔔");
  });
});

describe("NotificationsBell (GHG11(13): переключатель панели ленты)", () => {
  it("показывает бейдж с числом непрочитанных", async () => {
    mount();
    const badge = await screen.findByTestId("notifications-badge");
    expect(badge.textContent).toBe("2");
    expect(screen.getByTestId("notifications-bell").getAttribute("aria-label")).toBe(
      "Панель ленты, непрочитанных уведомлений: 2",
    );
  });

  it("клик выдвигает панель ленты, а не отдельный экран уведомлений", async () => {
    mount();
    await screen.findByTestId("notifications-badge");
    const bell = screen.getByTestId("notifications-bell");
    expect(bell.getAttribute("aria-expanded")).toBe("false");

    await act(async () => {
      fireEvent.click(bell);
    });

    expect(useUI.getState().feedPanel).toBe(true);
    fireEvent.click(bell);
    expect(useUI.getState().feedPanel).toBe(false);
    // Своего полноэкранного листа у колокольчика больше нет — ленту он не прячет.
    expect(screen.queryByTestId("notifications-sheet")).toBeNull();
  });

  it("список в панели рисует тексты и отмечает прочитанными", async () => {
    mountSheet();
    const rows = await screen.findAllByTestId("notification-row");
    expect(rows).toHaveLength(2);
    expect(screen.getByTestId("notifications-list").textContent).toContain(
      "Митян лайкнул твой трек «Гимн чата»",
    );
    await waitFor(() => expect(readNotifications).toHaveBeenCalledWith({ all: true }));
  });

  it("пустое состояние: никаких лайков — никаких строк", async () => {
    vi.mocked(fetchNotifications).mockResolvedValue({ unread: 0, items: [] });
    mountSheet();
    await screen.findByTestId("notifications-list");
    expect(await screen.findByText(/Пока тихо/)).toBeTruthy();
    expect(screen.queryByTestId("notification-row")).toBeNull();
    expect(readNotifications).not.toHaveBeenCalled(); // нечего отмечать
  });
});
