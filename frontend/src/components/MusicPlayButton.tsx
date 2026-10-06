/**
 * GHG11(6): кнопка «слушать» для трека, загруженного в бота.
 *
 * У таких треков (`kind='audio'`) есть только Telegram `file_id` — ссылки нет,
 * поэтому звук тянется блобом через `/api/game/music/tracks/{id}/audio` с
 * Authorization (элемент `<audio>` сам заголовки не умеет). Треки-ссылки
 * (`kind='link'`) играются по своему `url` — этот компонент им не нужен.
 *
 * Прод-баг: раньше кнопка «▶️» рисовалась ровно по наличию `url`, поэтому
 * загруженные в бота треки нельзя было послушать ни в ленте, ни в «Предложке».
 */
import { useEffect, useState, type MouseEvent } from "react";
import { fetchMusicAudioUrl } from "@/api/game";
import { haptic } from "@/tg/webapp";

export function MusicPlayButton({
  trackId,
  className,
}: {
  trackId: number;
  className?: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const play = async (e: MouseEvent) => {
    // Внутри ленты/строки клик по кнопке не должен раскрывать карточку.
    e.stopPropagation();
    haptic("light");
    if (url) {
      URL.revokeObjectURL(url);
      setUrl(null);
      return;
    }
    setLoading(true);
    try {
      setUrl(await fetchMusicAudioUrl(trackId));
    } catch {
      haptic("error");
    } finally {
      setLoading(false);
    }
  };

  // Не течём blob-URL'ами при закрытии ленты/подборки.
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );

  return (
    <>
      <button
        type="button"
        onClick={play}
        disabled={loading}
        className={[
          "shrink-0 rounded-full bg-tg-secondary-bg px-2 py-1 text-xs disabled:opacity-50",
          className ?? "",
        ].join(" ")}
        aria-label="Прослушать трек"
      >
        {loading ? "…" : url ? "⏸" : "▶️"}
      </button>
      {url && (
        <audio
          src={url}
          autoPlay
          onClick={(e) => e.stopPropagation()}
          onEnded={() => {
            URL.revokeObjectURL(url);
            setUrl(null);
          }}
        />
      )}
    </>
  );
}
