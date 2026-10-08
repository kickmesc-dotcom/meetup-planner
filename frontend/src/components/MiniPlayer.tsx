/**
 * GHG11(7): один общий мини-плеер для аудио-треков.
 *
 * Раньше у каждой точки (лента, «Предложка недели») была своя кнопка «▶️» с
 * отдельным `<audio>`: треки играли «в отрыве» — без прогресса, без перехода к
 * следующему треку и с потерей позиции при повторном тапе. Здесь один плеер на
 * подборку:
 *
 *  - прогресс с перемоткой (тап по полосе);
 *  - ⏮/⏭ — переключение между АУДИО-треками подборки (треки-ссылки
 *    открываются на своём источнике — в плеере их нет);
 *  - пауза НЕ сбрасывает позицию: держим один `<audio>` и просто `pause()`.
 *
 * GHG11(8): это ядро плеера. Очередь недели, показ поверх всех вкладок и
 * память «последний трек + позиция» надстроены сверху (`GlobalPlayer.tsx`):
 * с `persistKey` хук сам восстанавливает трек из localStorage.
 *
 * Звук треков, загруженных в бота (`kind='audio'`), тянется блобом с
 * Authorization через `fetchMusicAudioUrl` (элемент `<audio>` не умеет слать
 * заголовки). Блоб освобождаем при смене трека и на размонтирование.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { fetchMusicAudioUrl } from "@/api/game";
import { haptic } from "@/tg/webapp";

/** Трек в терминах плеера — общий для ленты и «Предложки недели». */
export interface MiniTrack {
  id: number;
  kind: string;
  title: string | null;
  performer: string | null;
  url?: string | null;
}

/** «Исполнитель — название» (или что есть). Общий для строк и плашки плеера. */
export function miniTrackLabel(t: {
  performer?: string | null;
  title?: string | null;
  url?: string | null;
}): string {
  if (t.performer && t.title && !t.title.includes(t.performer)) {
    return `${t.performer} — ${t.title}`;
  }
  return t.title || t.performer || t.url || "трек";
}

/** Секунды → `м:сс` для шкалы прогресса. */
export function formatTime(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/**
 * Где плеер помнит «последний трек и позицию» (GHG11(8)).
 *
 * `sessionStorage`-подобное поведение не подходит: участник закрывает мини-апп
 * и открывает заново — надо продолжить с того же места. Поэтому `localStorage`,
 * но доступ к нему аккуратный: в приватном режиме/старом webview его может не
 * быть — тогда плеер просто не переживёт перезапуск, но не упадёт.
 */
export interface PlayerSnapshot {
  id: number | null;
  time: number;
}

function readSnapshot(key: string): PlayerSnapshot | null {
  try {
    if (typeof localStorage === "undefined") return null;
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PlayerSnapshot>;
    const id = typeof parsed.id === "number" ? parsed.id : null;
    const time = typeof parsed.time === "number" && parsed.time > 0 ? parsed.time : 0;
    if (id === null) return null;
    return { id, time };
  } catch {
    return null;
  }
}

function writeSnapshot(key: string, snapshot: PlayerSnapshot): void {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(key, JSON.stringify(snapshot));
  } catch {
    // приватный режим или переполнение — не повод ронять плеер
  }
}

/** Забыть последний трек (пользователь закрыл плеер крестиком). */
export function clearPlayerSnapshot(key: string): void {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.removeItem(key);
  } catch {
    // ignore
  }
}

/**
 * Состояние плеера для одной подборки.
 *
 * Рендерит контролы `MiniPlayerBar`; логика (источник, игра/пауза, позиция)
 * живёт здесь, чтобы экраны не дублировали `<audio>`.
 *
 * GHG11(8): с `persistKey` плеер запоминает последний трек и позицию между
 * сессиями — восстановление происходит, как только очередь готова (см. ниже).
 */
/**
 * Треки, которые вообще можно проиграть: загруженные в бота (`kind='audio'`).
 * Ссылки играют на своём источнике — в очереди плеера их нет.
 */
export function playableTracks(tracks: MiniTrack[]): MiniTrack[] {
  return tracks.filter((t) => t.kind === "audio" && !t.url);
}

export function useMiniPlayer(
  tracks: MiniTrack[],
  opts?: { persistKey?: string },
) {
  const persistKey = opts?.persistKey;
  // Играем только треки, загруженные в бота: у ссылок нет blob-аудио.
  const playable = useMemo(() => playableTracks(tracks), [tracks]);

  const [currentId, setCurrentId] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [src, setSrc] = useState<string | null>(null);
  // GHG11(8): секунда из сохранённой сессии — прыгаем к ней, как только трек
  // получит метаданные (до этого `currentTime` выставить некуда).
  const [pendingSeek, setPendingSeek] = useState<number | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const blobRef = useRef<string | null>(null);
  const restoredRef = useRef(false);
  // GHG11(9): заготовленные блобы следующего трека. Скачиваем ЗАРАНЕЕ, пока
  // играет текущий, — тогда переход не ждёт сеть и не рвёт воспроизведение.
  const cacheRef = useRef<Map<number, string>>(new Map());
  // Актуальный трек для асинхронных заготовок: колбэк предзагрузки не должен
  // перечитывать устаревшее значение `currentId` из замыкания.
  const currentIdRef = useRef<number | null>(null);
  currentIdRef.current = currentId;

  // GHG11(8): восстановление последнего трека. Ждём, пока очередь готова
  // (в глобальном плеере она приезжает запросом «Подборка недели»), и делаем
  // это один раз — дальше состоянием управляет пользователь. Играть сразу НЕ
  // начинаем: автоплей в webview всё равно заблокирован, а «продолжить» —
  // осознанное действие.
  useEffect(() => {
    if (!persistKey || restoredRef.current || playable.length === 0) return;
    restoredRef.current = true;
    const saved = readSnapshot(persistKey);
    if (!saved || saved.id === null) return;
    if (!playable.some((t) => t.id === saved.id)) {
      clearPlayerSnapshot(persistKey);
      return;
    }
    setCurrentId(saved.id);
    setPlaying(false);
    if (saved.time > 1) setPendingSeek(saved.time);
  }, [persistKey, playable]);

  // GHG11(8): помним последний трек и позицию. Пишем не на каждый тик, а при
  // смене трека и при переходе на новую секунду; пустой `currentId` (закрытый
  // плеер) ничего не перезаписывает.
  useEffect(() => {
    if (!persistKey || currentId == null) return;
    writeSnapshot(persistKey, { id: currentId, time });
    // `Math.floor(time)` — дешёвое «раз в секунду» без лишних записей в LS.
  }, [persistKey, currentId, Math.floor(time)]);

  const revokeBlob = () => {
    // В старых webview / jsdom `revokeObjectURL` может отсутствовать — не падаем.
    if (blobRef.current && typeof URL.revokeObjectURL === "function") {
      URL.revokeObjectURL(blobRef.current);
    }
    blobRef.current = null;
  };

  // GHG11(9): текущий трек ищем по id и держим как ОБЪЕКТ.
  //
  // Это принципиально для «неприрываемого» плеера: при переключении режима или
  // перемешивании меняется только порядок (`playable` — новый массив, но те же
  // объекты из query-кэша). Если бы эффект ниже зависел от массива, он бы
  // перезагрузил текущий трек — то есть остановил музыку.
  const current = useMemo(
    () => playable.find((t) => t.id === currentId),
    [playable, currentId],
  );

  // Кто пойдёт следующим: последний трек очереди замыкается на первый.
  const nextId = useMemo(() => {
    if (playable.length === 0) return null;
    const i = playable.findIndex((t) => t.id === currentId);
    return playable[i < 0 ? 0 : (i + 1) % playable.length].id;
  }, [playable, currentId]);

  // Предзагрузка следующего трека. Ошибку глотаем: не вышло заготовить —
  // трек просто скачается в момент перехода, как было раньше.
  useEffect(() => {
    // Заготавливаем только когда что-то уже играет: до первого тапа скачивать
    // чужой блоб смысла нет.
    if (currentId == null) return;
    if (nextId == null || cacheRef.current.has(nextId) || nextId === currentId) return;
    let cancelled = false;
    fetchMusicAudioUrl(nextId)
      .then((url) => {
        const cache = cacheRef.current;
        if (cancelled) {
          if (typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
          return;
        }
        // Трек успели переключить, пока грузилось: кэшем больше не пользуются.
        if (currentIdRef.current !== nextId) {
          if (typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
          return;
        }
        cache.set(nextId, url);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps — currentIdRef вместо currentId
  }, [nextId, currentId]);

  // Смена трека: берём заготовленный блоб или тянем новый, старый освобождаем.
  useEffect(() => {
    if (currentId == null) {
      setSrc(null);
      revokeBlob();
      return;
    }
    if (!current) {
      setCurrentId(null);
      return;
    }
    setTime(0);
    setDuration(0);
    const prepared = cacheRef.current.get(current.id) ?? null;
    if (prepared) {
      // Заготовка есть — переключаемся сразу, без «паузы на загрузку».
      cacheRef.current.delete(current.id);
      revokeBlob();
      blobRef.current = prepared;
      setSrc(prepared);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    // Мгновенно останавливаем предыдущий трек, пока грузится новый.
    setSrc(null);
    fetchMusicAudioUrl(current.id)
      .then((url) => {
        if (cancelled) {
          if (typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
          return;
        }
        revokeBlob();
        blobRef.current = url;
        setSrc(url);
      })
      .catch(() => {
        if (cancelled) return;
        setPlaying(false);
        haptic("error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Зависимость — сам трек-объект, а не массив очереди (см. комментарий выше).
  }, [currentId, current]);

  // Играть/пауза. Пауза — только `pause()`: позиция сохраняется.
  useEffect(() => {
    const el = audioRef.current;
    if (!el || !src) return;
    if (playing) {
      const p = el.play();
      // jsdom и старые webview могут вернуть undefined — не падаем.
      if (p && typeof p.catch === "function") p.catch(() => setPlaying(false));
    } else {
      el.pause();
    }
  }, [playing, src]);

  // Не течём блоб-URL'ами при закрытии ленты/подборки — включая заготовки.
  useEffect(
    () => () => {
      revokeBlob();
      const cache = cacheRef.current;
      cache.forEach((url) => {
        if (typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
      });
      cache.clear();
    },
    [],
  );

  const select = (id: number) => {
    haptic("light");
    if (currentId === id) {
      setPlaying((v) => !v);
      return;
    }
    setCurrentId(id);
    setPlaying(true);
  };

  const toggle = () => {
    if (currentId == null) return;
    haptic("light");
    setPlaying((v) => !v);
  };

  const step = (dir: 1 | -1) => {
    if (playable.length === 0) return;
    haptic("light");
    const i = playable.findIndex((t) => t.id === currentId);
    const next = i < 0 ? 0 : (i + dir + playable.length) % playable.length;
    setCurrentId(playable[next].id);
    setPlaying(true);
  };

  // Закрыть плеер. GHG11(8): ещё и забываем сохранённую позицию — иначе
  // крестик «закрывал» плеер, а после перезапуска он возвращался сам.
  const stop = () => {
    setPlaying(false);
    // Плашка исчезает вместе с `<audio>`, но элемент, вынутый из документа,
    // по спецификации может продолжать играть — поэтому глушим явно.
    audioRef.current?.pause();
    setCurrentId(null);
    setPendingSeek(null);
    if (persistKey) clearPlayerSnapshot(persistKey);
  };

  /** Перемотка: доля 0..1 от длительности. */
  const seek = (fraction: number) => {
    const el = audioRef.current;
    if (!el || duration <= 0) return;
    const next = Math.max(0, Math.min(1, fraction)) * duration;
    el.currentTime = next;
    setTime(next);
  };

  const onEnded = () => {
    // GHG11(9): главное правило — НИКОГДА не прерывать воспроизведение.
    // Дальше по очереди, а на последнем треке — на первый (плейлисты по кругу);
    // если трек вообще один, крутим его же.
    if (playable.length > 1) {
      step(1);
      return;
    }
    const el = audioRef.current;
    if (el) {
      el.currentTime = 0;
      const p = el.play();
      if (p && typeof p.catch === "function") p.catch(() => setPlaying(false));
    }
    setPlaying(true);
  };

  const active = currentId != null;
  const index = playable.findIndex((t) => t.id === currentId);
  const isCurrent = (id: number) => currentId === id;
  const fraction = duration > 0 ? Math.min(1, time / duration) : 0;

  return {
    playable,
    active,
    playing,
    loading,
    time,
    duration,
    src,
    fraction,
    current,
    index,
    title: current ? miniTrackLabel(current) : "",
    select,
    toggle,
    step,
    stop,
    seek,
    onEnded,
    isCurrent,
    audioRef,
    onTimeUpdate: () => setTime(audioRef.current?.currentTime ?? 0),
    // Метаданные готовы: длительность + прыжок к сохранённой позиции (один раз).
    onLoadedMetadata: () => {
      const el = audioRef.current;
      setDuration(el?.duration ?? 0);
      if (el && pendingSeek != null && Number.isFinite(el.duration)) {
        const target = Math.min(pendingSeek, Math.max(0, el.duration - 0.25));
        el.currentTime = target;
        setTime(target);
      }
      setPendingSeek(null);
    },
  };
}

export type MiniPlayer = ReturnType<typeof useMiniPlayer>;

/** Плашка плеера: показывается под подборкой, пока выбран трек. */
export function MiniPlayerBar({
  player,
  className,
  extras,
}: {
  player: MiniPlayer;
  className?: string;
  /** GHG11(9): доп. контролы под строкой трека (SHUFFLE, «лайкнутые», ❤️). */
  extras?: ReactNode;
}) {
  if (!player.active) return null;
  const canSwitch = player.playable.length > 1;
  return (
    // GHG11(11): раскладка разведена на строки. Раньше название, время,
    // счётчик трека, транспорт и крестик делили ОДНУ линию: на узком экране
    // пять целей жались друг к другу, а длинное название выдавливало кнопки.
    // Теперь у каждой группы своя строка и свои отступы (gap-2):
    //   1) что играет + ✕;  2) транспорт по центру, справа — время и счётчик;
    //   3) полоса перемотки;  4) режимы/лайк (extras);  5) подпись подборки.
    <div
      data-testid="mini-player"
      className={[
        "flex flex-col gap-2 rounded-xl bg-tg-secondary-bg/80 px-3 py-2.5",
        className ?? "",
      ].join(" ")}
    >
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1 truncate text-xs font-medium text-tg-text">
          {player.title}
        </div>
        <button
          type="button"
          onClick={player.stop}
          aria-label="Закрыть плеер"
          className="-my-1 shrink-0 rounded-full px-1.5 text-sm text-tg-hint"
        >
          ✕
        </button>
      </div>

      <div className="grid grid-cols-[1fr_auto] items-center gap-2">
        <div className="flex items-center justify-center gap-4">
          <button
            type="button"
            onClick={() => player.step(-1)}
            disabled={!canSwitch}
            aria-label="Предыдущий трек"
            className="shrink-0 rounded-full bg-tg-bg/60 px-3 py-1.5 text-sm disabled:opacity-40"
          >
            ⏮
          </button>
          <button
            type="button"
            onClick={player.toggle}
            aria-label={player.playing ? "Пауза" : "Воспроизвести"}
            className="shrink-0 rounded-full bg-tg-bg/60 px-4 py-1.5 text-base"
          >
            {player.loading ? "…" : player.playing ? "⏸" : "▶️"}
          </button>
          <button
            type="button"
            onClick={() => player.step(1)}
            disabled={!canSwitch}
            aria-label="Следующий трек"
            className="shrink-0 rounded-full bg-tg-bg/60 px-3 py-1.5 text-sm disabled:opacity-40"
          >
            ⏭
          </button>
        </div>
        <div className="shrink-0 text-right text-[10px] leading-tight tabular-nums text-tg-hint">
          <div>
            {formatTime(player.time)} / {formatTime(player.duration)}
          </div>
          {canSwitch && (
            <div>
              трек {Math.max(1, player.index + 1)} из {player.playable.length}
            </div>
          )}
        </div>
      </div>

      {/* Полоса прогресса: тап по ней — перемотка. Сразу под транспортом,
          чтобы «где мы внутри трека» не отделялось от самих кнопок. */}
      <button
        type="button"
        aria-label="Перемотать"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          if (rect.width > 0) player.seek((e.clientX - rect.left) / rect.width);
        }}
        className="block h-4 w-full"
      >
        <span className="mt-1 block h-1.5 w-full overflow-hidden rounded-full bg-tg-bg/70">
          <span
            className="block h-full rounded-full bg-tg-link"
            style={{ width: `${player.fraction * 100}%` }}
          />
        </span>
      </button>

      {/* GHG11(9): доп. блок — режимы, лайк и подпись подборки. */}
      {extras && <div className="flex flex-col gap-1.5">{extras}</div>}

      <audio
        ref={player.audioRef}
        src={player.src ?? undefined}
        preload="metadata"
        onTimeUpdate={player.onTimeUpdate}
        onLoadedMetadata={player.onLoadedMetadata}
        onEnded={player.onEnded}
      />
    </div>
  );
}
