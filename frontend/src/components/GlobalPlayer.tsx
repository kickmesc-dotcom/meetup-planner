/**
 * GHG11(8): плеер подборки на всё приложение.
 * GHG11(9): плеер стал «плейлистом недель» — и главное правило теперь звучит так:
 * **воспроизведение не прерывается никогда**.
 *
 * Как это устроено:
 *
 *  - **очередь — это список подборок** (`GET /api/game/music/queue`), свежая
 *    первая; треки идут подряд, а после последней подборки очередь замыкается на
 *    первую (плейлисты по кругу). Раньше в очереди была ровно одна свежая
 *    подборка, и музыка упиралась в её конец;
 *  - **SHUFFLE** — честная перестановка всей очереди (Фишер–Йетс по seed), а не
 *    «случайный следующий трек»: включил — порядок один и тот же до следующего
 *    включения, выключил — вернулся естественный. Перемешивание НЕ перезапускает
 *    текущий трек: меняется только порядок;
 *  - **лайк прямо в плеере** и отдельный режим «играть только лайкнутые»;
 *  - трек, который играет сейчас, всегда остаётся в очереди — даже если режим
 *    сменился и его нет в новом наборе (иначе музыка бы обрывалась).
 *
 * Ядро (аудио, блоб, позиция, память между сессиями) живёт в `MiniPlayer.tsx`;
 * здесь — очередь, режимы и лайк.
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchMusicQueue, fetchMyMusic, likeMusicTrack } from "@/api/game";
import { haptic } from "@/tg/webapp";
import {
  MiniPlayerBar,
  playableTracks,
  useMiniPlayer,
  type MiniPlayer,
  type MiniTrack,
} from "./MiniPlayer";

/** Ключ в localStorage: «последний трек и позиция». */
export const PLAYER_PERSIST_KEY = "ghg.player.v1";

/**
 * GHG11(17): ключ в localStorage: сколько раз проигран каждый трек.
 *
 * Нужно правилу «реже повторяем»: когда выбранная подборка кончилась, плеер
 * не начинает сначала, а продолжает теми треками, которые звучали меньше всех.
 * Счётчик живёт между сессиями — иначе после перезапуска мини-аппа статистика
 * обнулялась бы и «редко звучащий» трек опять играл бы чаще.
 */
export const PLAY_COUNTS_KEY = "ghg.plays.v1";

/** Ключ источника «все подборки». */
export const SOURCE_ALL = "all";
/** Ключ источника «только лайкнутые». */
export const SOURCE_LIKED = "liked";

/** Сколько раз играл каждый трек. Никогда не бросает (приватный режим/мусор). */
export function readPlayCounts(): Record<number, number> {
  try {
    if (typeof localStorage === "undefined") return {};
    const raw = localStorage.getItem(PLAY_COUNTS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const out: Record<number, number> = {};
    for (const [key, value] of Object.entries(parsed ?? {})) {
      const id = Number(key);
      const n = Number(value);
      if (Number.isInteger(id) && Number.isFinite(n) && n > 0) out[id] = n;
    }
    return out;
  } catch {
    return {};
  }
}

/** Запомнить счётчики. Сбой хранилища не повод ронять плеер. */
export function writePlayCounts(counts: Record<number, number>): void {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(PLAY_COUNTS_KEY, JSON.stringify(counts));
  } catch {
    // ignore
  }
}

/**
 * GHG11(17): порядок «реже повторяем» — по возрастанию того, сколько трек уже
 * играл. Чистая функция (тесты).
 *
 * Устойчивая сортировка: те, кто не звучал ни разу (счётчик 0/отсутствует),
 * уходят вперёд и СОХРАНЯЮТ исходный порядок между собой — то есть в пределах
 * одной «частоты» очередь остаётся предсказуемой, а не перемешивается сама.
 */
export function leastPlayedOrder(
  tracks: MiniTrack[],
  counts: Record<number, number>,
): MiniTrack[] {
  return tracks
    .map((track, index) => ({ track, index, played: counts[track.id] ?? 0 }))
    .sort((a, b) => (a.played - b.played) || (a.index - b.index))
    .map((entry) => entry.track);
}

/** Лайк трека в терминах плеера: сколько всего и поставил ли его я. */
export interface TrackLikeState {
  likes: number;
  liked: boolean;
}

export interface PlayerPlaylist {
  key: string;
  title: string;
  tracks: MiniTrack[];
}

/**
 * Честный SHUFFLE: перестановка Фишер–Йетса с детерминированным PRNG.
 *
 * Почему не `sort(() => Math.random() - 0.5)`: тот и не равномерный, и
 * перетасовывает очередь при каждом рендере (трек «перескакивал» сам по себе).
 * Здесь один и тот же `seed` всегда даёт одну и ту же перестановку — очередь
 * меняется только когда её пересдают явно.
 */
export function shuffledTracks(tracks: MiniTrack[], seed: number): MiniTrack[] {
  const out = [...tracks];
  let state = (seed >>> 0) || 1;
  // xorshift32: дёшево, воспроизводимо, без зависимостей.
  const next = () => {
    state ^= state << 13;
    state >>>= 0;
    state ^= state >>> 17;
    state ^= state << 5;
    state >>>= 0;
    return state / 0xffffffff;
  };
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(next() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export type GlobalPlayer = MiniPlayer & {
  /**
   * Включить трек. Подборку (`collection`) больше НЕ подменяет очередь: трек
   * встаёт в голову очереди, а дальше плеер сам продолжит подборки — иначе тап в
   * ленте обрывал бы текущую музыку.
   */
  playTrack: (track: MiniTrack, collection?: MiniTrack[]) => void;
  /** Подборки очереди (для подписи «что играет» и переключателя режима). */
  playlists: PlayerPlaylist[];
  /** Название подборки, из которой играет текущий трек. */
  playlistTitle: string;
  /** Режим «играть только лайкнутые». */
  likedMode: boolean;
  toggleLikedMode: () => void;
  /** Честный SHUFFLE всей очереди. */
  shuffle: boolean;
  toggleShuffle: () => void;
  /** Сколько лайкнутых треков вообще есть — для подписи кнопки режима. */
  likedCount: number;
  /**
   * GHG11(17): что выбрано источником звука: `all` | `liked` | ключ подборки.
   * Шит выбора подборки подсвечивает по нему текущую строку.
   */
  sourceKey: string;
  /**
   * GHG11(17): выбрать источник и сразу начать его играть.
   *
   * `opts.shuffle` — заодно переключить перемешивание (нужно кнопке «слушать
   * всё случайно»): выбор источника и режим порядка — одно действие для человека.
   */
  chooseSource: (key: string, opts?: { shuffle?: boolean }) => void;
  /** Лайк текущего трека (или `null`, если трек вне подборок). */
  currentLikes: TrackLikeState | null;
  toggleLike: () => void;
  likePending: boolean;
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
  playlists: [],
  playlistTitle: "",
  likedMode: false,
  toggleLikedMode: () => {},
  shuffle: false,
  toggleShuffle: () => {},
  likedCount: 0,
  sourceKey: SOURCE_ALL,
  chooseSource: () => {},
  currentLikes: null,
  toggleLike: () => {},
  likePending: false,
};

const PlayerContext = createContext<GlobalPlayer>(NOOP_PLAYER);

/** Плеер приложения. Вне провайдера возвращает безопасную заглушку. */
export function useGlobalPlayer(): GlobalPlayer {
  return useContext(PlayerContext);
}

export function PlayerProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  // Тот же ключ, что у экрана музыки: react-query отдаст один и тот же кэш.
  const music = useQuery({
    queryKey: ["music", "mine"],
    queryFn: fetchMyMusic,
    staleTime: 60_000,
  });
  const queue = useQuery({
    queryKey: ["music", "queue"],
    queryFn: fetchMusicQueue,
    staleTime: 60_000,
  });

  /** Подборки очереди (только играбельные треки, пустые не показываем). */
  const playlists = useMemo<PlayerPlaylist[]>(
    () =>
      (queue.data?.playlists ?? [])
        .map((pl) => ({
          key: pl.key,
          title: pl.title,
          tracks: playableTracks(pl.tracks),
        }))
        .filter((pl) => pl.tracks.length > 0),
    [queue.data],
  );
  const likedTracks = useMemo(
    () => playableTracks(queue.data?.liked ?? []),
    [queue.data],
  );
  // Фолбэк, если новая ручка ещё не уехала на сервер: играем свежую подборку,
  // как раньше (GHG11(8)).
  const fallbackWeek = useMemo(
    () => playableTracks(music.data?.week?.tracks ?? []),
    [music.data],
  );

  const [likedMode, setLikedMode] = useState(false);
  // GHG11(17): выбранная подборка («слушаю именно эту неделю»). `null` — все
  // подборки подряд, как раньше. Когда выбранная подборка кончится, очередь не
  // замкнётся на её первый трек, а продолжится «реже повторяемыми» (см. ниже).
  const [weekKey, setWeekKey] = useState<string | null>(null);
  const [shuffle, setShuffle] = useState(false);
  const [seed, setSeed] = useState(1);
  // GHG11(17): сколько раз играл каждый трек — между сессиями.
  const [playCounts, setPlayCounts] = useState<Record<number, number>>(
    readPlayCounts,
  );
  // Треки, включённые точечно (например, из ленты): стоят впереди очереди.
  const [extra, setExtra] = useState<MiniTrack[]>([]);
  // Текущий трек «пришпиливаем» к очереди: смена режима не должна обрывать звук.
  const anchorRef = useRef<MiniTrack | null>(null);
  const [anchorId, setAnchorId] = useState<number | null>(null);

  /** Все играбельные треки библиотеки (все подборки + лайкнутые, без дублей). */
  const library = useMemo(() => {
    const seen = new Set<number>();
    const out: MiniTrack[] = [];
    const push = (tracks: MiniTrack[]) => {
      for (const track of tracks) {
        if (seen.has(track.id)) continue;
        seen.add(track.id);
        out.push(track);
      }
    };
    for (const pl of playlists) push(pl.tracks);
    push(likedTracks);
    if (out.length === 0) push(fallbackWeek);
    return out;
  }, [playlists, likedTracks, fallbackWeek]);

  const chosenWeek = useMemo(
    () => (weekKey ? playlists.find((pl) => pl.key === weekKey) ?? null : null),
    [weekKey, playlists],
  );

  const base = useMemo(() => {
    let source: MiniTrack[];
    if (likedMode) {
      source = likedTracks;
    } else if (chosenWeek) {
      // GHG11(17): играем выбранную подборку, а потом — «реже повторяемое» из
      // остальной библиотеки. Так музыка не обрывается на конце подборки и не
      // зацикливается на ней, пока вокруг полно других треков.
      const own = new Set(chosenWeek.tracks.map((t) => t.id));
      const tail = leastPlayedOrder(
        library.filter((t) => !own.has(t.id)),
        playCounts,
      );
      source = [...chosenWeek.tracks, ...tail];
    } else {
      source =
        playlists.length > 0 ? playlists.flatMap((pl) => pl.tracks) : fallbackWeek;
    }
    if (extra.length === 0) return source;
    const ids = new Set(source.map((t) => t.id));
    return [...extra.filter((t) => !ids.has(t.id)), ...source];
  }, [likedMode, likedTracks, chosenWeek, library, playCounts, playlists, fallbackWeek, extra]);

  /** Очередь воспроизведения: «пришпиленный» трек + режим + перемешивание. */
  const order = useMemo(() => {
    const anchored =
      anchorId != null && anchorRef.current && !base.some((t) => t.id === anchorId)
        ? [anchorRef.current, ...base]
        : base;
    return shuffle ? shuffledTracks(anchored, seed) : anchored;
  }, [base, shuffle, seed, anchorId]);

  const player = useMiniPlayer(order, { persistKey: PLAYER_PERSIST_KEY });

  // Через ref: `select` пересоздаётся каждый рендер, а `playTrack` должен быть
  // стабильным, чтобы не дёргать потребителей лишний раз.
  const playerRef = useRef(player);
  playerRef.current = player;

  // Помним, что играет, чтобы не потерять этот трек при смене режима/шафла.
  useEffect(() => {
    if (player.current && anchorRef.current?.id !== player.current.id) {
      anchorRef.current = player.current;
      setAnchorId(player.current.id);
    }
  }, [player.current]);

  // GHG11(17): считаем сыгранное для правила «реже повторяем». Засчитываем РОВНО
  // один раз на каждое начало трека и только когда звук реально пошёл: пауза и
  // восстановление последнего трека из localStorage в статистику не попадают.
  const countedRef = useRef<number | null>(null);
  useEffect(() => {
    const id = player.current?.id ?? null;
    if (id == null) {
      countedRef.current = null;
      return;
    }
    if (!player.playing || countedRef.current === id) return;
    countedRef.current = id;
    setPlayCounts((prev) => {
      const next = { ...prev, [id]: (prev[id] ?? 0) + 1 };
      writePlayCounts(next);
      return next;
    });
  }, [player.current, player.playing]);

  const playTrack = useCallback((track: MiniTrack, collection?: MiniTrack[]) => {
    haptic("light");
    const extraTracks = collection?.length ? playableTracks(collection) : [track];
    setExtra((prev) => {
      const seen = new Set(prev.map((t) => t.id));
      const added = extraTracks.filter((t) => !seen.has(t.id));
      return added.length === 0 ? prev : [...prev, ...added];
    });
    if (collection?.length) {
      // Трек мог не попасть в очередь (лента играет и старые треки) — пусть
      // встанет впереди, а дальше плеер подхватит подборки.
      anchorRef.current = track;
      setAnchorId(track.id);
    }
    playerRef.current.select(track.id);
  }, []);

  // ---------------------------------------------------------------- лайки ----
  const likesById = useMemo(() => {
    const map = new Map<number, TrackLikeState>();
    for (const pl of queue.data?.playlists ?? []) {
      for (const t of pl.tracks) map.set(t.id, { likes: t.likes, liked: t.liked });
    }
    for (const t of queue.data?.liked ?? []) {
      if (!map.has(t.id)) map.set(t.id, { likes: t.likes, liked: t.liked });
    }
    for (const t of music.data?.week?.tracks ?? []) {
      if (!map.has(t.id)) map.set(t.id, { likes: t.likes, liked: t.liked });
    }
    return map;
  }, [queue.data, music.data]);
  // Оптимистичное состояние: ответ сервера важнее кэша, но до рефетча живём им.
  const [likeOverride, setLikeOverride] = useState<Record<number, TrackLikeState>>({});

  const likeMutation = useMutation({
    mutationFn: (trackId: number) => likeMusicTrack(trackId),
    onSuccess: (res, trackId) => {
      setLikeOverride((prev) => ({
        ...prev,
        [trackId]: { likes: res.likes, liked: res.liked },
      }));
      haptic(res.liked ? "success" : "light");
      void qc.invalidateQueries({ queryKey: ["music", "queue"] });
      void qc.invalidateQueries({ queryKey: ["music", "mine"] });
    },
    onError: () => haptic("error"),
  });

  const currentId = player.current?.id ?? null;
  const currentLikes = useMemo(() => {
    if (currentId == null) return null;
    return likeOverride[currentId] ?? likesById.get(currentId) ?? null;
  }, [currentId, likeOverride, likesById]);

  const toggleLike = useCallback(() => {
    if (currentId == null || currentLikes == null) return;
    haptic("light");
    likeMutation.mutate(currentId);
  }, [currentId, currentLikes, likeMutation]);

  const toggleShuffle = useCallback(() => {
    haptic("light");
    setShuffle((on) => {
      // Пересдаём перестановку на каждом включении: «честный свитчер» должен
      // давать НОВЫЙ порядок, а не тот же самый.
      if (!on) setSeed((s) => s + 1);
      return !on;
    });
  }, []);

  const toggleLikedMode = useCallback(() => {
    haptic("light");
    setLikedMode((on) => !on);
  }, []);

  /**
   * Все треки, которые плеер вообще может сыграть, по id.
   *
   * Нужно, чтобы `select(id)` работал не только для очереди: подборки недели —
   * не единственный вход (лента играет и треки прошлых недель, экран музыки —
   * свежую подборку). Такой трек «пришпиливаем» в голову очереди, а дальше
   * плеер сам продолжит подборки.
   */
  const knownById = useMemo(() => {
    const map = new Map<number, MiniTrack>();
    for (const pl of queue.data?.playlists ?? []) {
      for (const t of pl.tracks) map.set(t.id, t);
    }
    for (const t of queue.data?.liked ?? []) {
      if (!map.has(t.id)) map.set(t.id, t);
    }
    for (const t of fallbackWeek) {
      if (!map.has(t.id)) map.set(t.id, t);
    }
    for (const t of extra) {
      if (!map.has(t.id)) map.set(t.id, t);
    }
    return map;
  }, [queue.data, fallbackWeek, extra]);

  /**
   * Выбор трека, который умеет то, чего не умеет ядро: если трека нет в очереди,
   * он встаёт в её начало (и остаётся там — «пришпилен»), а не молча теряется.
   */
  const select = useCallback(
    (id: number) => {
      if (!order.some((t) => t.id === id)) {
        const track = knownById.get(id);
        if (track) {
          anchorRef.current = track;
          setAnchorId(track.id);
          setExtra((prev) => (prev.some((t) => t.id === id) ? prev : [...prev, track]));
        }
      }
      playerRef.current.select(id);
    },
    [order, knownById],
  );

  const playlistTitle = useMemo(() => {
    if (currentId == null) return "";
    if (likedMode) return "Только лайкнутые";
    const owner = playlists.find((pl) => pl.tracks.some((t) => t.id === currentId));
    return owner?.title ?? "Вне подборок";
  }, [currentId, likedMode, playlists]);

  /**
   * GHG11(17): что выберет слушатель — треки выбранного источника в том же
   * порядке, в каком их сложит очередь (подборка → «реже повторяемое»).
   */
  const tracksForSource = useCallback(
    (key: string): MiniTrack[] => {
      if (key === SOURCE_LIKED) return likedTracks;
      if (key === SOURCE_ALL) {
        return playlists.length > 0
          ? playlists.flatMap((pl) => pl.tracks)
          : fallbackWeek;
      }
      const pl = playlists.find((p) => p.key === key);
      if (!pl) return [];
      const own = new Set(pl.tracks.map((t) => t.id));
      return [
        ...pl.tracks,
        ...leastPlayedOrder(
          library.filter((t) => !own.has(t.id)),
          playCounts,
        ),
      ];
    },
    [likedTracks, playlists, fallbackWeek, library, playCounts],
  );

  /** Текущий источник звука — по нему шит выбора подсвечивает строку. */
  const sourceKey = likedMode ? SOURCE_LIKED : chosenWeek ? chosenWeek.key : SOURCE_ALL;

  /**
   * GHG11(17): выбрать источник и сразу начать его играть.
   *
   * `opts.shuffle` — заодно переключить перемешивание: «слушать всё случайно»
   * для человека одно действие, а не два (выбрать источник + потом найти тумблер).
   */
  const chooseSource = useCallback(
    (key: string, opts?: { shuffle?: boolean }) => {
      haptic("light");
      setLikedMode(key === SOURCE_LIKED);
      setWeekKey(key === SOURCE_ALL || key === SOURCE_LIKED ? null : key);
      let nextSeed = seed;
      if (opts?.shuffle !== undefined) {
        setShuffle(opts.shuffle);
        if (opts.shuffle) {
          // Новая перестановка на каждое включение: «случайно» не должно дважды
          // давать один и тот же порядок.
          nextSeed = seed + 1;
          setSeed(nextSeed);
        }
      }
      const tracks = tracksForSource(key);
      const first =
        (opts?.shuffle ?? shuffle)
          ? shuffledTracks(tracks, nextSeed)[0]
          : tracks[0];
      if (first) select(first.id);
    },
    [seed, shuffle, tracksForSource, select],
  );

  const value = useMemo<GlobalPlayer>(
    () => ({
      ...player,
      select,
      playTrack,
      playlists,
      playlistTitle,
      likedMode,
      toggleLikedMode,
      shuffle,
      toggleShuffle,
      likedCount: likedTracks.length,
      sourceKey,
      chooseSource,
      currentLikes,
      toggleLike,
      likePending: likeMutation.isPending,
    }),
    [
      player,
      select,
      playTrack,
      playlists,
      playlistTitle,
      likedMode,
      toggleLikedMode,
      shuffle,
      toggleShuffle,
      likedTracks.length,
      sourceKey,
      chooseSource,
      currentLikes,
      toggleLike,
      likeMutation.isPending,
    ],
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
  const likeLabel = player.currentLikes?.liked ? "Убрать лайк" : "Лайкнуть трек";
  return (
    <div className="shrink-0 px-3 pb-1 pt-2">
      <MiniPlayerBar
        player={player}
        extras={
          <>
            {/* GHG11(11): режимы и лайк — в одну спокойную строку (лайк у
                правого края), а подпись подборки — отдельной строкой. Раньше
                четыре элемента теснились в один ряд и подпись отжимала кнопки. */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                data-testid="player-shuffle"
                aria-pressed={player.shuffle}
                aria-label="Перемешать очередь"
                onClick={player.toggleShuffle}
                className={[
                  "shrink-0 rounded-full px-2.5 py-1 text-2xs font-medium",
                  player.shuffle
                    ? "bg-tg-button text-tg-button-text"
                    : "bg-tg-bg/60 text-tg-hint",
                ].join(" ")}
              >
                🔀 SHUFFLE
              </button>
              <button
                type="button"
                data-testid="player-liked-mode"
                aria-pressed={player.likedMode}
                onClick={player.toggleLikedMode}
                className={[
                  "shrink-0 rounded-full px-2.5 py-1 text-2xs font-medium",
                  player.likedMode
                    ? "bg-tg-button text-tg-button-text"
                    : "bg-tg-bg/60 text-tg-hint",
                ].join(" ")}
              >
                ❤️ лайкнутые{player.likedCount > 0 ? ` (${player.likedCount})` : ""}
              </button>
              {player.currentLikes && (
                <button
                  type="button"
                  data-testid="player-like"
                  aria-label={likeLabel}
                  aria-pressed={player.currentLikes.liked}
                  disabled={player.likePending}
                  onClick={player.toggleLike}
                  className="ml-auto shrink-0 rounded-full bg-tg-bg/60 px-2.5 py-1 text-2xs font-medium text-tg-text disabled:opacity-50"
                >
                  {player.currentLikes.liked ? "❤️" : "🤍"} {player.currentLikes.likes}
                </button>
              )}
            </div>
            <div className="truncate text-2xs text-tg-hint">
              {player.playlistTitle}
            </div>
          </>
        }
      />
    </div>
  );
}
