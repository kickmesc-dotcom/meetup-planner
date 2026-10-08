// @vitest-environment jsdom
/**
 * GHG11(9): плеер как «плейлист недель» (главное правило — не прерывать плейбек).
 *
 * Проверяем обещания из запроса оператора:
 *  - подборки играются подряд, а после последней очередь идёт по кругу;
 *  - SHUFFLE — честная перестановка очереди, и переключение НЕ перезапускает
 *    текущий трек (не тянет его звук заново);
 *  - режим «только лайкнутые» тоже не обрывает то, что играет сейчас;
 *  - лайк ставится прямо из плашки;
 *  - следующий трек скачивается заранее (переход без ожидания сети).
 */
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  PLAYER_PERSIST_KEY,
  PlayerBar,
  PlayerProvider,
  shuffledTracks,
  useGlobalPlayer,
} from "./GlobalPlayer";
import type { MiniTrack } from "./MiniPlayer";
import {
  fetchMusicAudioUrl,
  fetchMusicQueue,
  fetchMyMusic,
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
    likeMusicTrack: vi.fn(),
  };
});

const AUDIO = (id: number, title: string): MiniTrack => ({
  id,
  kind: "audio",
  title,
  performer: null,
  url: null,
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
      tracks: [WEEK_TRACK(1, "Неделя-1-а", 2), WEEK_TRACK(2, "Неделя-1-б")],
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
  vi.mocked(fetchMusicAudioUrl).mockImplementation(
    async (id: number) => `blob:${id}`,
  );
  vi.mocked(fetchMusicQueue).mockResolvedValue(QUEUE);
  vi.mocked(fetchMyMusic).mockResolvedValue({
    enabled: true,
    week: { tracks: [] },
  } as unknown as MusicMine);
  vi.mocked(likeMusicTrack).mockResolvedValue({ ok: true, liked: true, likes: 5 });
});

afterEach(cleanup);

function Harness() {
  const player = useGlobalPlayer();
  return (
    <>
      <button type="button" aria-label="select-1" onClick={() => player.select(1)}>
        1
      </button>
      <button type="button" aria-label="select-7" onClick={() => player.select(7)}>
        7
      </button>
      {/* Маркер загрузки очереди: без него тап может случиться раньше, чем
          приедут подборки (и тогда трека просто нет в очереди). */}
      <span data-testid="playlists">{player.playlists.length}</span>
      <PlayerBar />
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
  // Ждём очередь из мокнутого API: 2 подборки = данные дошли до плеера.
  await waitFor(() =>
    expect(screen.getByTestId("playlists").textContent).toBe("2"),
  );
  return view;
}

async function startTrackOne() {
  const view = await mount();
  await act(async () => {
    fireEvent.click(screen.getByLabelText("select-1"));
  });
  await screen.findByTestId("mini-player");
  return view;
}

// --------------------------------------------------------------------------
// SHUFFLE как перестановка (чистая функция)
// --------------------------------------------------------------------------
describe("shuffledTracks: честный SHUFFLE", () => {
  const tracks = [AUDIO(1, "a"), AUDIO(2, "b"), AUDIO(3, "c"), AUDIO(4, "d")];

  it("детерминирован: один seed — один порядок", () => {
    expect(shuffledTracks(tracks, 42).map((t) => t.id)).toEqual(
      shuffledTracks(tracks, 42).map((t) => t.id),
    );
  });

  it("это именно перестановка: ничего не теряется и не дублируется", () => {
    const out = shuffledTracks(tracks, 7);
    expect(out).toHaveLength(tracks.length);
    expect([...out].map((t) => t.id).sort()).toEqual([1, 2, 3, 4]);
    // оригинал не мутируем — очередь в состоянии не должна меняться «на месте»
    expect(tracks.map((t) => t.id)).toEqual([1, 2, 3, 4]);
  });

  it("разные seed дают разные порядки (хотя бы иногда)", () => {
    const a = shuffledTracks(tracks, 1).map((t) => t.id).join(",");
    const b = shuffledTracks(tracks, 2).map((t) => t.id).join(",");
    expect(a).not.toEqual(b);
  });

  it("пустая очередь и один трек не ломаются", () => {
    expect(shuffledTracks([], 5)).toEqual([]);
    expect(shuffledTracks([AUDIO(9, "один")], 5)).toEqual([AUDIO(9, "один")]);
  });
});

// --------------------------------------------------------------------------
// очередь из подборок
// --------------------------------------------------------------------------
describe("PlayerProvider: плейлисты недель", () => {
  it("подборки играются подряд и замыкаются по кругу", async () => {
    await startTrackOne();
    const bar = screen.getByTestId("mini-player");
    expect(bar.textContent).toContain("Неделя-1-а");
    expect(bar.textContent).toContain("трек 1 из 3");
    // подпись — из подборки, а не «вне подборок»
    expect(bar.textContent).toContain("Подборка недели");

    const next = screen.getByLabelText("Следующий трек");
    fireEvent.click(next);
    expect(screen.getByTestId("mini-player").textContent).toContain("Неделя-1-б");

    fireEvent.click(next);
    const third = screen.getByTestId("mini-player");
    expect(third.textContent).toContain("Старая-а");
    expect(third.textContent).toContain("Подборка от 01.10.2026");

    // конец очереди — не конец музыки: возвращаемся к первой подборке
    fireEvent.click(next);
    expect(screen.getByTestId("mini-player").textContent).toContain("Неделя-1-а");
  });

  it("по окончании последнего трека очередь идёт по кругу", async () => {
    const { container } = await startTrackOne();
    const audio = container.querySelector("audio")!;
    const next = screen.getByLabelText("Следующий трек");

    fireEvent.click(next); // 2
    fireEvent.click(next); // 3 — последний
    expect(screen.getByTestId("mini-player").textContent).toContain("Старая-а");

    await act(async () => {
      fireEvent(audio, new Event("ended"));
    });
    expect(screen.getByTestId("mini-player").textContent).toContain("Неделя-1-а");
  });

  it("предзагружает следующий трек, пока играет текущий", async () => {
    await startTrackOne();
    const asked = vi.mocked(fetchMusicAudioUrl).mock.calls.map((c) => c[0]);
    expect(asked).toContain(1);
    expect(asked).toContain(2); // заготовка следующего — переход без ожидания
  });
});

// --------------------------------------------------------------------------
// «не прерывать плейбек»
// --------------------------------------------------------------------------
describe("PlayerProvider: воспроизведение не прерывается", () => {
  it("SHUFFLE не перезапускает текущий трек", async () => {
    await startTrackOne();
    const before = vi.mocked(fetchMusicAudioUrl).mock.calls.length;

    await act(async () => {
      fireEvent.click(screen.getByTestId("player-shuffle"));
    });

    expect(screen.getByTestId("mini-player").textContent).toContain("Неделя-1-а");
    // Текущий трек не перекачиваем: меняется только порядок, звук не рвётся.
    expect(vi.mocked(fetchMusicAudioUrl).mock.calls.length).toBeLessThanOrEqual(
      before + 1, // +1 — возможная заготовка нового «следующего»
    );
    expect(vi.mocked(fetchMusicAudioUrl).mock.calls.map((c) => c[0])).not.toContain(
      undefined,
    );
    expect(screen.getByTestId("player-shuffle").getAttribute("aria-pressed")).toBe(
      "true",
    );
  });

  it("режим «лайкнутые» не обрывает трек, которого нет в лайкнутых", async () => {
    await startTrackOne();

    await act(async () => {
      fireEvent.click(screen.getByTestId("player-liked-mode"));
    });

    const bar = screen.getByTestId("mini-player");
    expect(bar.textContent).toContain("Неделя-1-а"); // «пришпилен» к очереди
    expect(bar.textContent).toContain("Только лайкнутые");

    // Дальше — из лайкнутых: очередь реально сменилась
    fireEvent.click(screen.getByLabelText("Следующий трек"));
    expect(screen.getByTestId("mini-player").textContent).toContain("Лайкнутая");
  });

  it("клик по лайкнутому треку работает и в выключенном режиме", async () => {
    await mount();
    await act(async () => {
      fireEvent.click(screen.getByLabelText("select-7"));
    });
    const bar = await screen.findByTestId("mini-player");
    expect(bar.textContent).toContain("Лайкнутая");
    expect(localStorage.getItem(PLAYER_PERSIST_KEY)).toContain('"id":7');
  });
});

// --------------------------------------------------------------------------
// лайк из плеера
// --------------------------------------------------------------------------
describe("PlayerBar: лайк трека", () => {
  it("ставит лайк текущему треку и показывает новое число", async () => {
    await startTrackOne();
    const like = screen.getByTestId("player-like");
    expect(like.textContent).toContain("2"); // из очереди (likes: 2)
    expect(like.getAttribute("aria-pressed")).toBe("false");

    await act(async () => {
      fireEvent.click(like);
    });

    expect(vi.mocked(likeMusicTrack).mock.calls[0][0]).toBe(1);
    const after = screen.getByTestId("player-like");
    expect(after.textContent).toContain("❤️");
    expect(after.textContent).toContain("5"); // ответ сервера важнее кэша
    expect(after.getAttribute("aria-pressed")).toBe("true");
  });

  it("в режиме лайкнутых кнопка лайка не пропадает", async () => {
    await mount();
    await act(async () => {
      fireEvent.click(screen.getByLabelText("select-7"));
    });
    await screen.findByTestId("mini-player");
    expect(screen.getByTestId("player-like").textContent).toContain("5");
  });
});
