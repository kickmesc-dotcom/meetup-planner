/**
 * GHG8 H.7 / GHG10 Э15/Э17: экран мини-аппа «Предложка недели».
 *
 * Участник видит СВОИ сданные треки, остаток недельного лимита, свежую
 * подборку с лайками, топ треков недели и историю уже выпущенных подборок.
 * Чужие треки до публикации не показываем — интрига сохраняется (и сервер их
 * не отдаёт). Сдавать треки можно только боту в личку; здесь — витрина.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addMusicTrack,
  fetchMyMusic,
  likeMusicTrack,
  type MusicMineTrack,
  type MusicWeek,
  type MusicWeekTrack,
} from "@/api/game";
import { ListSkeleton } from "@/components/Skeleton";
import { MiniPlayerBar, useMiniPlayer } from "@/components/MiniPlayer";
import { haptic, showAlert } from "@/tg/webapp";

function statusLabel(status: string): { text: string; className: string } {
  if (status === "published") {
    return { text: "в подборке", className: "bg-tg-button/20 text-tg-link" };
  }
  if (status === "removed") {
    return { text: "убрано", className: "bg-tg-bg/60 text-tg-hint" };
  }
  return { text: "в очереди", className: "bg-tg-bg/60 text-tg-hint" };
}

function trackTitle(t: {
  performer: string | null;
  title: string | null;
  url?: string | null;
}): string {
  if (t.performer && t.title && !t.title.includes(t.performer)) {
    return `${t.performer} — ${t.title}`;
  }
  return t.title || t.performer || t.url || "трек";
}

function shortDate(value: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

/** Кнопка лайка: тап ставит/снимает реакцию и обновляет экран. */
function LikeButton({ track }: { track: MusicWeekTrack }) {
  const queryClient = useQueryClient();
  const like = useMutation({
    mutationFn: () => likeMusicTrack(track.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["music", "mine"] });
    },
  });
  return (
    <button
      type="button"
      onClick={() => like.mutate()}
      disabled={like.isPending}
      className="shrink-0 rounded-md bg-tg-bg/60 px-2 py-1 text-xs tabular-nums disabled:opacity-50"
      aria-label={track.liked ? "Убрать лайк" : "Поставить лайк"}
    >
      {track.liked ? "❤️" : "🤍"} {track.likes}
    </button>
  );
}

/** Э21: сдача трека ссылкой прямо в мини-аппе (аудиофайл — боту в личку). */
function AddTrackForm() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const add = useMutation({
    mutationFn: () =>
      addMusicTrack({ url: url.trim(), title: title.trim() || undefined }),
    onSuccess: (res) => {
      if (res.ok) {
        haptic("success");
        setUrl("");
        setTitle("");
        void queryClient.invalidateQueries({ queryKey: ["music", "mine"] });
      } else {
        haptic("error");
        void showAlert(addTrackStatus(res.status));
      }
    },
    onError: () => haptic("error"),
  });
  return (
    <div className="mt-3 space-y-1.5 border-t border-tg-bg/40 pt-3">
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https:// ссылка на трек"
        inputMode="url"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        className="w-full rounded-lg bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
      />
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Название (необязательно)"
        className="w-full rounded-lg bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
      />
      <button
        type="button"
        disabled={add.isPending || !url.trim()}
        onClick={() => {
          haptic("selection");
          add.mutate();
        }}
        className="w-full rounded-lg bg-tg-button px-3 py-2 text-sm font-medium text-tg-button-text active:scale-[0.98] disabled:opacity-50"
      >
        {add.isPending ? "Добавляем…" : "Добавить трек по ссылке"}
      </button>
    </div>
  );
}

function addTrackStatus(status: string): string {
  switch (status) {
    case "limit":
      return "На эту неделю лимит треков уже исчерпан.";
    case "duplicate":
      return "Такой трек уже сдан.";
    case "bad":
      return "Не похоже на ссылку — проверь адрес.";
    case "unknown_user":
      return "Тебя нет в списке участников.";
    default:
      return "Не получилось добавить трек.";
  }
}

/**
 * GHG11(7): «Подборка недели» с общим мини-плеером.
 *
 * Раньше на каждый трек была отдельная кнопка со своим `<audio>` — без
 * прогресса и переключения. Теперь один плеер на подборку: тап по кнопке
 * трека выбирает его, дальше работают ⏮/⏭/пауза (пауза сохраняет позицию).
 * Ссылки по-прежнему открываются на своём источнике — плеер их не ведёт.
 */
function WeekTracksSection({ week }: { week: MusicWeek }) {
  const player = useMiniPlayer(week.tracks);
  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-base font-semibold">📻 Подборка недели</div>
        <span className="shrink-0 text-xs tabular-nums text-tg-hint">
          {shortDate(week.created_at)}
        </span>
      </div>
      <div className="mb-2 text-xs text-tg-hint">
        Ткни лайк — лучшие попадут в топ недели.
      </div>
      <div className="divide-y divide-tg-bg/40">
        {week.tracks.map((t) => (
          <div key={t.id} className="flex items-center gap-2 py-2">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm">{trackTitle(t)}</div>
              {t.kind === "link" && t.url && (
                <div className="truncate text-[11px] text-tg-hint">
                  {t.url}
                </div>
              )}
            </div>
            {t.kind === "audio" ? (
              <button
                type="button"
                onClick={() => player.select(t.id)}
                className="shrink-0 rounded-full bg-tg-secondary-bg px-2 py-1 text-xs"
                aria-label="Прослушать трек"
              >
                {player.isCurrent(t.id) && player.playing ? "⏸" : "▶️"}
              </button>
            ) : t.kind === "link" && t.url ? (
              <a
                href={t.url}
                target="_blank"
                rel="noreferrer"
                className="shrink-0 rounded-full bg-tg-secondary-bg px-2 py-1 text-xs"
                aria-label="Открыть трек"
              >
                ▶️
              </a>
            ) : null}
            <LikeButton track={t} />
          </div>
        ))}
      </div>
      <MiniPlayerBar player={player} className="mt-2" />
    </section>
  );
}

export function MusicScreen() {
  const music = useQuery({ queryKey: ["music", "mine"], queryFn: fetchMyMusic });
  const data = music.data;

  if (music.isPending) {
    return (
      <div className="flex-1 overflow-y-auto p-3">
        <ListSkeleton rows={4} />
      </div>
    );
  }

  if (!data?.enabled) {
    return (
      <div className="flex-1 overflow-y-auto p-3">
        <section className="rounded-xl bg-tg-secondary-bg/60 p-4 text-sm text-tg-hint">
          🎧 Музыкальная предложка сейчас выключена.
        </section>
      </div>
    );
  }

  const left = Math.max(0, data.per_user_weekly - data.week_count);
  // Бэкенд может быть чуть старше фронта (Cloudflare Pages пересобирается
  // раньше HF/Amvera): без Э17 в ответе нет `week`/`top` — не падаем.
  const week = data.week ?? null;
  const top = data.top ?? [];

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      <section className="rounded-xl bg-tg-secondary-bg/60 p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="text-base font-semibold">🎧 Моя неделя</div>
          <span className="shrink-0 rounded-md bg-tg-bg/60 px-2 py-0.5 text-xs tabular-nums text-tg-hint">
            осталось {left} из {data.per_user_weekly}
          </span>
        </div>
        <div className="mt-1 text-xs text-tg-hint">
          Кидай треки боту в личку — аудиофайлом или ссылкой. Раз в неделю бот
          выкладывает подборку в чат.
        </div>
        {/* Э21: ссылку можно сдать прямо здесь (аудио — по-прежнему боту). */}
        <AddTrackForm />
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold">Сдано на этой неделе</div>
        <div className="mb-2 text-xs text-tg-hint">
          {data.tracks.length
            ? `${data.tracks.length} из ${data.per_user_weekly}`
            : "Пока пусто"}
        </div>
        {!data.tracks.length ? (
          <div className="py-2 text-xs text-tg-hint">
            Ничего не сдано. Открой чат с ботом и скинь первый трек.
          </div>
        ) : (
          <div className="divide-y divide-tg-bg/40">
            {data.tracks.map((t: MusicMineTrack) => {
              const badge = statusLabel(t.status);
              return (
                <div key={t.id} className="flex items-center gap-2 py-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm">{trackTitle(t)}</div>
                    {t.kind === "link" && t.url && (
                      <div className="truncate text-[11px] text-tg-hint">
                        {t.url}
                      </div>
                    )}
                  </div>
                  <span
                    className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] ${badge.className}`}
                  >
                    {badge.text}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {week && week.tracks.length > 0 && <WeekTracksSection week={week} />}

      {top.length > 0 && (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
          <div className="text-base font-semibold">🏆 Топ недели</div>
          <div className="mb-2 text-xs text-tg-hint">По лайкам за 7 дней</div>
          <div className="divide-y divide-tg-bg/40">
            {top.map((t, i) => (
              <div key={t.id} className="flex items-center gap-2 py-2">
                <span className="w-5 shrink-0 text-center text-xs tabular-nums text-tg-hint">
                  {i + 1}
                </span>
                <div className="min-w-0 flex-1 truncate text-sm">
                  {trackTitle(t)}
                </div>
                <span className="shrink-0 text-xs tabular-nums text-tg-hint">
                  ❤️ {t.likes}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold">📀 Прошлые подборки</div>
        <div className="mb-2 text-xs text-tg-hint">Последние 10 сборок</div>
        {!data.history.length ? (
          <div className="py-2 text-xs text-tg-hint">Подборок ещё не было.</div>
        ) : (
          <div className="divide-y divide-tg-bg/40">
            {data.history.map((s) => (
              <div key={s.id} className="flex items-center gap-2 py-2">
                <div className="flex-1 text-sm">
                  Подборка из <span className="tabular-nums">{s.track_count}</span>{" "}
                  треков
                </div>
                <span className="shrink-0 text-xs tabular-nums text-tg-hint">
                  {shortDate(s.created_at)}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
