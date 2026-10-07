/**
 * GHG11(8): плеер подборки на всё приложение.
 *
 * Раньше мини-плеер жил внутри конкретной подборки (лента / «Предложка недели»):
 * сменил вкладку — музыка пропала, а очередь ограничивалась тем, что на экране.
 * Здесь плеер один на весь мини-апп:
 *
 *  - **очередь** — все аудио-треки подборки недели; ⏭/авто-переход идут по ней;
 *  - **поверх вкладок** — плашка стоит в общем каркасе, рядом с таб-баром;
 *  - **между сессиями** — последний трек и позиция лежат в `localStorage`,
 *    после перезапуска трек восстанавливается (пауза, кнопка «продолжить»).
 *
 * Провайдер добывает очередь из того же запроса «Подборка недели», что и экран
 * музыки, поэтому данные не дублируются. Экраны получают плеер через
 * `useGlobalPlayer()` и просто включают нужный трек.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchMyMusic } from "@/api/game";
import {
  MiniPlayerBar,
  playableTracks,
  useMiniPlayer,
  type MiniPlayer,
  type MiniTrack,
} from "./MiniPlayer";

/** Ключ в localStorage: «последний трек и позиция». */
export const PLAYER_PERSIST_KEY = "ghg.player.v1";

export type GlobalPlayer = MiniPlayer & {
  /**
   * Включить трек. `collection` — подборка, из которой его ткнули: она и станет
   * новой очередью (иначе очередь остаётся прежней, а трек добавляется в конец).
   */
  playTrack: (track: MiniTrack, collection?: MiniTrack[]) => void;
};

/** Заглушка для тестов/экранов без провайдера: ничего не играет, но не падает. */
const NOOP_PLAYER: GlobalPlayer = {
  playable: [],
  active: false,
  playing: false,
  loading: false,
  time: 0,
  duration: 0,
  src: null,
  fraction: 0,
  current: undefined,
  index: -1,
  title: "",
  select: () => {},
  toggle: () => {},
  step: () => {},
  stop: () => {},
  seek: () => {},
  onEnded: () => {},
  isCurrent: () => false,
  audioRef: { current: null },
  onTimeUpdate: () => {},
  onLoadedMetadata: () => {},
  playTrack: () => {},
};

const PlayerContext = createContext<GlobalPlayer>(NOOP_PLAYER);

/** Плеер приложения. Вне провайдера возвращает безопасную заглушку. */
export function useGlobalPlayer(): GlobalPlayer {
  return useContext(PlayerContext);
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  // Тот же ключ, что у экрана музыки: react-query отдаст один и тот же кэш.
  const music = useQuery({
    queryKey: ["music", "mine"],
    queryFn: fetchMyMusic,
    staleTime: 60_000,
  });
  const weekQueue = useMemo(
    () => playableTracks(music.data?.week?.tracks ?? []),
    [music.data],
  );
  const [queue, setQueue] = useState<MiniTrack[]>(weekQueue);
  useEffect(() => {
    // Очередь недели — источник по умолчанию. Пока запрос не пришёл, живём с
    // тем, что уже есть (после восстановления сессии очередь придёт следом).
    if (weekQueue.length > 0) setQueue(weekQueue);
  }, [weekQueue]);

  const player = useMiniPlayer(queue, { persistKey: PLAYER_PERSIST_KEY });

  // Через ref: `select` пересоздаётся каждый рендер, а `playTrack` должен быть
  // стабильным, чтобы не дёргать потребителей лишний раз.
  const playerRef = useRef(player);
  playerRef.current = player;

  const playTrack = useCallback((track: MiniTrack, collection?: MiniTrack[]) => {
    if (collection && collection.length > 0) {
      const next = playableTracks(collection);
      setQueue(next.some((t) => t.id === track.id) ? next : [...next, track]);
    }
    playerRef.current.select(track.id);
  }, []);

  const value = useMemo<GlobalPlayer>(
    () => ({ ...player, playTrack }),
    [player, playTrack],
  );

  return (
    <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>
  );
}

/**
 * Плашка плеера в общем каркасе (между экраном и таб-баром) — поэтому она видна
 * на всех вкладках. Сама плашка возвращает `null`, пока трек не выбран.
 */
export function PlayerBar() {
  const player = useGlobalPlayer();
  if (!player.active) return null;
  return (
    <div className="shrink-0 px-3 pb-1 pt-2">
      <MiniPlayerBar player={player} />
    </div>
  );
}
