// @vitest-environment jsdom
/**
 * GHG11(8): плеер подборки на всё приложение.
 *
 * Проверяем три обещания из запроса:
 *  - очередь — все аудио-треки подборки, ссылки в неё не попадают;
 *  - авто-переход к следующему треку по окончании;
 *  - последний трек и позиция переживают перезапуск (localStorage).
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MiniPlayerBar, useMiniPlayer, type MiniTrack } from "./MiniPlayer";
import {
  PLAYER_PERSIST_KEY,
  PlayerBar,
  PlayerProvider,
  useGlobalPlayer,
} from "./GlobalPlayer";
import { fetchMusicAudioUrl, fetchMyMusic, type MusicMine } from "@/api/game";

vi.mock("@/api/game", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/game")>();
  return {
    ...actual,
    fetchMusicAudioUrl: vi.fn(),
    fetchMyMusic: vi.fn(),
  };
});

const KEY = "ghg-player-test";

const TRACKS: MiniTrack[] = [
  { id: 1, kind: "audio", title: "Первый", performer: "Автор", url: null },
  { id: 2, kind: "audio", title: "Второй", performer: null, url: null },
  { id: 3, kind: "audio", title: "Третий", performer: null, url: null },
  {
    id: 4,
    kind: "link",
    title: "Ссылочный",
    performer: null,
    url: "https://youtu.be/x",
  },
];

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

afterEach(cleanup);

function PersistHarness({
  tracks = TRACKS,
  persistKey,
}: {
  tracks?: MiniTrack[];
  persistKey?: string;
}) {
  const player = useMiniPlayer(tracks, { persistKey });
  return (
    <>
      {player.playable.map((t) => (
        <button
          key={t.id}
          type="button"
          aria-label={`play-${t.id}`}
          onClick={() => player.select(t.id)}
        >
          {t.id}
        </button>
      ))}
      <MiniPlayerBar player={player} />
    </>
  );
}

describe("useMiniPlayer: память между сессиями (GHG11(8))", () => {
  it("восстанавливает последний трек и позицию из localStorage", async () => {
    vi.mocked(fetchMusicAudioUrl).mockResolvedValue("blob:x");
    localStorage.setItem(KEY, JSON.stringify({ id: 2, time: 42 }));

    const { container } = render(<PersistHarness persistKey={KEY} />);

    const bar = await screen.findByTestId("mini-player");
    expect(bar.textContent).toContain("Второй");
    // Играть сразу не начинаем — автоплей в webview заблокирован.
    expect(screen.getByLabelText("Воспроизвести")).toBeTruthy();

    // Метаданные приходят позже — тогда и прыгаем к сохранённой секунде.
    const audio = container.querySelector("audio")!;
    Object.defineProperty(audio, "duration", { value: 100, configurable: true });
    await act(async () => {
      fireEvent(audio, new Event("loadedmetadata"));
    });
    expect(screen.getByTestId("mini-player").textContent).toContain(
      "0:42 / 1:40",
    );
  });

  it("без сохранённого трека плеер молчит", () => {
    render(<PersistHarness persistKey={KEY} />);
    expect(screen.queryByTestId("mini-player")).toBeNull();
  });

  it("крестик закрывает плеер и забывает трек", async () => {
    vi.mocked(fetchMusicAudioUrl).mockResolvedValue("blob:x");
    localStorage.setItem(KEY, JSON.stringify({ id: 1, time: 5 }));

    render(<PersistHarness persistKey={KEY} />);
    await screen.findByTestId("mini-player");
    fireEvent.click(screen.getByLabelText("Закрыть плеер"));

    expect(screen.queryByTestId("mini-player")).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("по окончании трека сам идёт к следующему (авто-переход)", async () => {
    vi.mocked(fetchMusicAudioUrl).mockResolvedValue("blob:x");
    const { container } = render(<PersistHarness />);

    fireEvent.click(screen.getByLabelText("play-1"));
    await screen.findByTestId("mini-player");
    const audio = container.querySelector("audio")!;
    await act(async () => {
      fireEvent(audio, new Event("ended"));
    });

    const bar = screen.getByTestId("mini-player");
    expect(bar.textContent).toContain("Второй");
    expect(bar.textContent).toContain("трек 2 из 3");
  });
});

describe("PlayerProvider: очередь недели (GHG11(8))", () => {
  function ConsumerHarness({
    track,
    collection,
  }: {
    track: MiniTrack;
    collection: MiniTrack[];
  }) {
    const player = useGlobalPlayer();
    return (
      <button type="button" onClick={() => player.playTrack(track, collection)}>
        go
      </button>
    );
  }

  it("playTrack ставит подборку в очередь и запускает трек", async () => {
    vi.mocked(fetchMusicAudioUrl).mockResolvedValue("blob:x");
    vi.mocked(fetchMyMusic).mockResolvedValue({
      enabled: true,
      week: { tracks: TRACKS },
    } as unknown as MusicMine);

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <PlayerProvider>
          <ConsumerHarness track={TRACKS[1]} collection={TRACKS} />
          <PlayerBar />
        </PlayerProvider>
      </QueryClientProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByText("go"));
    });

    const bar = await screen.findByTestId("mini-player");
    // Ссылка (id=4) в очередь не попала: 3 аудио-трека, играем второй.
    expect(bar.textContent).toContain("Второй");
    expect(bar.textContent).toContain("трек 2 из 3");
    expect(localStorage.getItem(PLAYER_PERSIST_KEY)).toContain('"id":2');
  });

  it("вне провайдера плеер безопасен (заглушка)", () => {
    function Bare() {
      const player = useGlobalPlayer();
      return <span>{player.active ? "играет" : "тихо"}</span>;
    }
    render(<Bare />);
    expect(screen.getByText("тихо")).toBeTruthy();
  });
});
