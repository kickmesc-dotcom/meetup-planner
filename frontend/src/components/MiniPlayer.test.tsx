// @vitest-environment jsdom
/**
 * GHG11(7): общий мини-плеер аудио-треков.
 *
 * Проверяем ключевые обещания: один плеер на подборку, переключение между
 * аудио-треками (⏮/⏭), пауза сохраняет позицию (трек не сбрасывается),
 * треки-ссылки в плеер не попадают.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  MiniPlayerBar,
  formatTime,
  miniTrackLabel,
  useMiniPlayer,
  type MiniTrack,
} from "./MiniPlayer";
import { fetchMusicAudioUrl } from "@/api/game";

vi.mock("@/api/game", () => ({
  fetchMusicAudioUrl: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const TRACKS: MiniTrack[] = [
  { id: 1, kind: "audio", title: "Первый", performer: "Автор", url: null },
  { id: 2, kind: "audio", title: "Второй", performer: null, url: null },
  {
    id: 3,
    kind: "link",
    title: "Ссылочный",
    performer: null,
    url: "https://youtu.be/x",
  },
];

/** Харнесс: плеер + кнопки выбора треков, как в реальных строках подборки. */
function Harness({ tracks = TRACKS }: { tracks?: MiniTrack[] }) {
  const player = useMiniPlayer(tracks);
  return (
    <>
      {player.playable.map((t) => (
        <button
          key={t.id}
          type="button"
          aria-label={`play-${t.id}`}
          onClick={() => player.select(t.id)}
        >
          {player.isCurrent(t.id) && player.playing ? "⏸" : "▶️"}
        </button>
      ))}
      <MiniPlayerBar player={player} />
    </>
  );
}

describe("useMiniPlayer: форматирование", () => {
  it("formatTime показывает м:сс", () => {
    expect(formatTime(0)).toBe("0:00");
    expect(formatTime(65)).toBe("1:05");
    expect(formatTime(600)).toBe("10:00");
  });

  it("miniTrackLabel склеивает исполнителя и название без дубля", () => {
    expect(miniTrackLabel({ performer: "Автор", title: "Песня" })).toBe(
      "Автор — Песня",
    );
    expect(miniTrackLabel({ performer: "Автор", title: "Автор — Песня" })).toBe(
      "Автор — Песня",
    );
  });
});

describe("MiniPlayerBar (GHG11(7))", () => {
  it("до выбора трека плеера нет", () => {
    render(<Harness />);
    expect(screen.queryByTestId("mini-player")).toBeNull();
  });

  it("в подборке только аудио-треки, ссылки не играются", () => {
    render(<Harness />);
    // Две кнопки для audio-треков, ссылочного (id=3) среди них нет.
    expect(screen.getByLabelText("play-1")).toBeTruthy();
    expect(screen.getByLabelText("play-2")).toBeTruthy();
    expect(screen.queryByLabelText("play-3")).toBeNull();
  });

  it("тап по треку открывает плеер и показывает название", async () => {
    vi.mocked(fetchMusicAudioUrl).mockResolvedValue("blob:one");
    render(<Harness />);
    fireEvent.click(screen.getByLabelText("play-1"));
    const bar = await screen.findByTestId("mini-player");
    expect(bar.textContent).toContain("Автор — Первый");
    expect(bar.textContent).toContain("трек 1 из 2");
    expect(fetchMusicAudioUrl).toHaveBeenCalledWith(1);
  });

  it("⏭ переключает на следующий трек подборки", async () => {
    vi.mocked(fetchMusicAudioUrl).mockResolvedValue("blob:x");
    render(<Harness />);
    fireEvent.click(screen.getByLabelText("play-1"));
    await screen.findByTestId("mini-player");
    fireEvent.click(screen.getByLabelText("Следующий трек"));
    expect(screen.getByTestId("mini-player").textContent).toContain("Второй");
    expect(screen.getByTestId("mini-player").textContent).toContain("трек 2 из 2");
  });

  it("пауза не закрывает плеер (позиция сохраняется)", async () => {
    vi.mocked(fetchMusicAudioUrl).mockResolvedValue("blob:x");
    render(<Harness />);
    fireEvent.click(screen.getByLabelText("play-1"));
    await screen.findByTestId("mini-player");
    expect(screen.getByLabelText("Пауза")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Пауза"));
    // Плеер остался на месте, просто перешёл в состояние «Воспроизвести».
    expect(screen.getByTestId("mini-player")).toBeTruthy();
    expect(screen.getByLabelText("Воспроизвести")).toBeTruthy();
  });

  it("✕ закрывает плеер", async () => {
    vi.mocked(fetchMusicAudioUrl).mockResolvedValue("blob:x");
    render(<Harness />);
    fireEvent.click(screen.getByLabelText("play-1"));
    await screen.findByTestId("mini-player");
    fireEvent.click(screen.getByLabelText("Закрыть плеер"));
    expect(screen.queryByTestId("mini-player")).toBeNull();
  });
});
