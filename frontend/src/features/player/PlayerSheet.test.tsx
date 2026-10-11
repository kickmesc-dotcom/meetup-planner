// @vitest-environment jsdom
/**
 * GHG11(17): вход в плеер в шапке ленты (бывший колокольчик) и шит выбора.
 *
 * Проверяем обещания запроса:
 *  - кнопка в шапке открывает шит с подборками и режимами прослушивания;
 *  - выбор подборки конкретной недели РЕАЛЬНО начинает её играть и закрывает шит
 *    (человек пришёл слушать, а не изучать настройки);
 *  - «всё вперемешку» включает перемешивание, «всё подряд» — выключает;
 *  - личные уведомления не выброшены — они открываются из шита плеера.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PlayerBar, PlayerProvider } from "@/components/GlobalPlayer";
import { PlayerButton } from "./PlayerSheet";
import PlayerSheet from "./PlayerSheet";
import { useUI } from "@/store/ui";
import {
  fetchMusicAudioUrl,
  fetchMusicQueue,
  fetchMyMusic,
  fetchNotifications,
  likeMusicTrack,
  type MusicMine,
  type MusicQueue,
  type MusicWeekTrack,
} from "@/api/game";

vi.mock("@/api/game", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/game")>();
  return {
    ...actual,
    fetchMusicAudioUrl: vi.fn(),
    fetchMyMusic: vi.fn(),
    fetchMusicQueue: vi.fn(),
    fetchNotifications: vi.fn(),
    readNotifications: vi.fn(),
    likeMusicTrack: vi.fn(),
  };
});

const WEEK_TRACK = (
  id: number,
  title: string,
  likes = 0,
  liked = false,
): MusicWeekTrack => ({
  id,
  kind: "audio",
  title,
  performer: null,
  url: null,
  likes,
  liked,
});

const QUEUE: MusicQueue = {
  enabled: true,
  playlists: [
    {
      key: "week:2",
      title: "Подборка недели",
      created_at: null,
      tracks: [WEEK_TRACK(1, "Неделя-1-а"), WEEK_TRACK(2, "Неделя-1-б")],
    },
    {
      key: "week:1",
      title: "Подборка от 01.10.2026",
      created_at: null,
      tracks: [WEEK_TRACK(3, "Старая-а")],
    },
  ],
  liked: [WEEK_TRACK(7, "Лайкнутая", 5, true)],
};

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  useUI.setState({ showPlayerSheet: false, showNotificationsSheet: false });
  vi.mocked(fetchMusicAudioUrl).mockImplementation(async (id: number) => `blob:${id}`);
  vi.mocked(fetchMusicQueue).mockResolvedValue(QUEUE);
  vi.mocked(fetchMyMusic).mockResolvedValue({
    enabled: true,
    week: { tracks: [] },
  } as unknown as MusicMine);
  vi.mocked(fetchNotifications).mockResolvedValue({ unread: 0, items: [] });
  vi.mocked(likeMusicTrack).mockResolvedValue({ ok: true, liked: true, likes: 6 });
});

afterEach(cleanup);

/** Как в App: шит рисуется только когда его открыл стор. */
function SheetSlot() {
  const open = useUI((s) => s.showPlayerSheet);
  return open ? <PlayerSheet /> : null;
}

function Harness() {
  return (
    <>
      <PlayerButton />
      {/* Как в App: плашка плеера в каркасе, шит — поверх. */}
      <PlayerBar />
      <SheetSlot />
    </>
  );
}

async function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <PlayerProvider>
        <Harness />
      </PlayerProvider>
    </QueryClientProvider>,
  );
  // Очередь приезжает запросом — без неё подборкам неоткуда взяться.
  await waitFor(() =>
    expect(useUI.getState().showPlayerSheet).toBe(false),
  );
  return view;
}

async function openSheet() {
  const view = await mount();
  await act(async () => {
    fireEvent.click(screen.getByTestId("player-launcher"));
  });
  await screen.findByTestId("player-sheet");
  return view;
}

describe("PlayerButton: вход вместо колокольчика", () => {
  it("открывает шит плеера, а не панель уведомлений", async () => {
    await mount();
    const launcher = screen.getByTestId("player-launcher");
    expect(launcher.getAttribute("aria-haspopup")).toBe("dialog");
    expect(launcher.textContent).toContain("🎧");

    await act(async () => {
      fireEvent.click(launcher);
    });
    expect(useUI.getState().showPlayerSheet).toBe(true);
    expect(useUI.getState().showNotificationsSheet).toBe(false);
    expect(screen.getByText("🎧 Музыка")).toBeTruthy();
  });

  it("показывает точку, когда музыка идёт", async () => {
    await openSheet();
    expect(screen.queryByTestId("player-launcher-dot")).toBeNull();
    await act(async () => {
      fireEvent.click(screen.getByTestId("player-source-all"));
    });
    await screen.findByTestId("mini-player");
    expect(screen.getByTestId("player-launcher-dot")).toBeTruthy();
  });
});

describe("PlayerSheet: выбор источника", () => {
  it("перечисляет подборки по неделям и режимы прослушивания", async () => {
    await openSheet();
    expect(screen.getByTestId("player-source-all")).toBeTruthy();
    expect(screen.getByTestId("player-source-shuffle")).toBeTruthy();
    expect(screen.getByTestId("player-source-liked")).toBeTruthy();
    expect(screen.getByTestId("player-source-week:1").textContent).toContain(
      "Подборка от 01.10.2026",
    );
    expect(screen.getByTestId("player-source-week:2").textContent).toContain(
      "Подборка недели",
    );
  });

  it("выбор подборки недели играет ЕЁ первый трек и закрывает шит", async () => {
    await openSheet();
    await act(async () => {
      fireEvent.click(screen.getByTestId("player-source-week:1"));
    });

    // Шит закрылся: выбор = «начать слушать», а не «настроить и остаться».
    expect(useUI.getState().showPlayerSheet).toBe(false);
    const bar = await screen.findByTestId("mini-player");
    expect(bar.textContent).toContain("Старая-а");
  });

  it("«всё вперемешку» включает SHUFFLE, «всё подряд» — выключает", async () => {
    await openSheet();
    await act(async () => {
      fireEvent.click(screen.getByTestId("player-source-shuffle"));
    });
    await screen.findByTestId("mini-player");
    expect(screen.getByTestId("player-shuffle").getAttribute("aria-pressed")).toBe(
      "true",
    );

    await act(async () => {
      fireEvent.click(screen.getByTestId("player-launcher"));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("player-source-all"));
    });
    expect(screen.getByTestId("player-shuffle").getAttribute("aria-pressed")).toBe(
      "false",
    );
  });

  it("выбранная строка подсвечена (aria-pressed)", async () => {
    await openSheet();
    await act(async () => {
      fireEvent.click(screen.getByTestId("player-source-week:2"));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("player-launcher"));
    });
    expect(screen.getByTestId("player-source-week:2").getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(screen.getByTestId("player-source-all").getAttribute("aria-pressed")).toBe(
      "false",
    );
  });
});

describe("PlayerSheet: уведомления не потерялись", () => {
  it("открывает шит личных уведомлений вместо плеера", async () => {
    vi.mocked(fetchNotifications).mockResolvedValue({
      unread: 3,
      items: [],
    });
    await openSheet();
    const row = await screen.findByTestId("player-sheet-notifications");
    expect(row.textContent).toContain("3");

    await act(async () => {
      fireEvent.click(row);
    });
    expect(useUI.getState().showPlayerSheet).toBe(false);
    expect(useUI.getState().showNotificationsSheet).toBe(true);
  });
});
