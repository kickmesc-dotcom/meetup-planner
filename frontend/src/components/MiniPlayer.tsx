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
 * Звук треков, загруженных в бота (`kind='audio'`), тянется блобом с
 * Authorization через `fetchMusicAudioUrl` (элемент `<audio>` не умеет слать
 * заголовки). Блоб освобождаем при смене трека и на размонтирование.
 */
import { useEffect, useMemo, useRef, useState } from "react";
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
 * Состояние плеера для одной подборки.
 *
 * Рендерит контролы `MiniPlayerBar`; логика (источник, игра/пауза, позиция)
 * живёт здесь, чтобы экраны не дублировали `<audio>`.
 */
export function useMiniPlayer(tracks: MiniTrack[]) {
  // Играем только треки, загруженные в бота: у ссылок нет blob-аудио.
  const playable = useMemo(
    () => tracks.filter((t) => t.kind === "audio" && !t.url),
    [tracks],
  );

  const [currentId, setCurrentId] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [src, setSrc] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const blobRef = useRef<string | null>(null);

  const revokeBlob = () => {
    // В старых webview / jsdom `revokeObjectURL` может отсутствовать — не падаем.
    if (blobRef.current && typeof URL.revokeObjectURL === "function") {
      URL.revokeObjectURL(blobRef.current);
    }
    blobRef.current = null;
  };

  // Смена трека: тянем новый источник, старый блоб освобождаем.
  useEffect(() => {
    if (currentId == null) {
      setSrc(null);
      revokeBlob();
      return;
    }
    const track = playable.find((t) => t.id === currentId);
    if (!track) {
      setCurrentId(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setTime(0);
    setDuration(0);
    // Мгновенно останавливаем предыдущий трек, пока грузится новый.
    setSrc(null);
    fetchMusicAudioUrl(track.id)
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
    // `playable` стабилен, пока стабилен массив `tracks` из query-кэша.
  }, [currentId, playable]);

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

  // Не течём блоб-URL'ами при закрытии ленты/подборки.
  useEffect(() => () => revokeBlob(), []);

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

  const stop = () => {
    setPlaying(false);
    setCurrentId(null);
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
    // Один трек в подборке — просто останавливаемся; иначе идём дальше.
    if (playable.length > 1) step(1);
    else setPlaying(false);
  };

  const active = currentId != null;
  const index = playable.findIndex((t) => t.id === currentId);
  const current = index >= 0 ? playable[index] : undefined;
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
    onLoadedMetadata: () => setDuration(audioRef.current?.duration ?? 0),
  };
}

export type MiniPlayer = ReturnType<typeof useMiniPlayer>;

/** Плашка плеера: показывается под подборкой, пока выбран трек. */
export function MiniPlayerBar({
  player,
  className,
}: {
  player: MiniPlayer;
  className?: string;
}) {
  if (!player.active) return null;
  const canSwitch = player.playable.length > 1;
  return (
    <div
      data-testid="mini-player"
      className={[
        "rounded-xl bg-tg-secondary-bg/80 px-2.5 py-2",
        className ?? "",
      ].join(" ")}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => player.step(-1)}
          disabled={!canSwitch}
          aria-label="Предыдущий трек"
          className="shrink-0 rounded-full bg-tg-bg/60 px-2 py-1 text-xs disabled:opacity-40"
        >
          ⏮
        </button>
        <button
          type="button"
          onClick={player.toggle}
          aria-label={player.playing ? "Пауза" : "Воспроизвести"}
          className="shrink-0 rounded-full bg-tg-bg/60 px-2.5 py-1 text-sm"
        >
          {player.loading ? "…" : player.playing ? "⏸" : "▶️"}
        </button>
        <button
          type="button"
          onClick={() => player.step(1)}
          disabled={!canSwitch}
          aria-label="Следующий трек"
          className="shrink-0 rounded-full bg-tg-bg/60 px-2 py-1 text-xs disabled:opacity-40"
        >
          ⏭
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium text-tg-text">
            {player.title}
          </div>
          {canSwitch && (
            <div className="text-[10px] tabular-nums text-tg-hint">
              трек {Math.max(1, player.index + 1)} из {player.playable.length}
            </div>
          )}
        </div>
        <span className="shrink-0 text-[10px] tabular-nums text-tg-hint">
          {formatTime(player.time)} / {formatTime(player.duration)}
        </span>
        <button
          type="button"
          onClick={player.stop}
          aria-label="Закрыть плеер"
          className="shrink-0 rounded-full px-1.5 text-sm text-tg-hint"
        >
          ✕
        </button>
      </div>

      {/* Полоса прогресса: тап по ней — перемотка. */}
      <button
        type="button"
        aria-label="Перемотать"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          if (rect.width > 0) player.seek((e.clientX - rect.left) / rect.width);
        }}
        className="mt-1.5 block h-4 w-full"
      >
        <span className="mt-1 block h-1.5 w-full overflow-hidden rounded-full bg-tg-bg/70">
          <span
            className="block h-full rounded-full bg-tg-link"
            style={{ width: `${player.fraction * 100}%` }}
          />
        </span>
      </button>

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
