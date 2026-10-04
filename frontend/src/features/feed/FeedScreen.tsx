import { useEffect, useState, type MouseEvent } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  fetchFeed,
  fetchVoiceAudioUrl,
  likeMusicTrack,
  FEED_KIND_LABELS,
  type FeedDetail,
  type FeedItem,
} from "@/api/game";
import ActivitiesPanel from "./ActivitiesPanel";
import AutoPickSheet from "@/features/actions/AutoPickSheet";
import LoserSheet from "@/features/actions/LoserSheet";
import PollSheet from "@/features/actions/PollSheet";
import { Spinner } from "@/components/Spinner";
import ErrorState from "@/components/ErrorState";
import { useUI } from "@/store/ui";
import { haptic, showAlert } from "@/tg/webapp";
import { fetchMe } from "@/api/availability";
import { triggerRandomPhrases } from "@/api/admin";
import { humanizeApiError } from "@/api/client";

/**
 * Э20: лента активности.
 *
 * Главная поверхность двух софт-режимов приглушения бота:
 *  - «ачивки в приложение» — сюда уезжают анонсы ачивок (в чате их нет);
 *  - «всё в приложение» — сюда уезжает вся активность (роллы, чуханы, события).
 *
 * Лента общая; переключатель «Все / Только мои» сужает её до записей игрока.
 * Клик по аватарке участника открывает его гостевой профиль (как на календаре).
 */
export default function FeedScreen({ meId }: { meId: number }) {
  const [scope, setScope] = useState<"all" | "mine">("all");
  // Э21: фильтр по типам. Пустое множество = «все типы».
  const [kinds, setKinds] = useState<Set<string>>(new Set());
  // GHG11: чтобы лента занимала максимум места, фильтры по категориям и панель
  // действий свёрнуты и раскрываются по клику в шапке.
  const [showFilters, setShowFilters] = useState(false);
  const [showActions, setShowActions] = useState(false);
  const openGuest = useUI((s) => s.openGuest);
  // Кнопка «Действие» переиспользует готовые шиты календаря (они читают флаги
  // из общего стора), поэтому монтируем их и здесь.
  const showLoser = useUI((s) => s.showLoserSheet);
  const showAuto = useUI((s) => s.showAutoPickSheet);
  const showPoll = useUI((s) => s.showPollSheet);
  const kindsParam = [...kinds].sort().join(",");

  const q = useInfiniteQuery({
    queryKey: ["game-feed", scope, kindsParam],
    queryFn: ({ pageParam }) =>
      fetchFeed({
        scope,
        limit: 30,
        offset: pageParam,
        kinds: kindsParam || undefined,
      }),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_offset ?? undefined,
  });

  const first = q.data?.pages[0];

  const availableKinds = first?.kinds ?? Object.keys(FEED_KIND_LABELS);
  const toggleKind = (k: string) => {
    haptic("selection");
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  if (q.isPending) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (q.isError) {
    return (
      <ErrorState
        error={q.error}
        onRetry={() => q.refetch()}
        title="Не удалось загрузить ленту"
      />
    );
  }

  const items: FeedItem[] = q.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* GHG11: компактная шапка — заголовок в одну строку, а строка управления
          (охват + фильтры + действие) сразу под ним. Максимум места — ленте. */}
      <div className="border-b border-tg-secondary-bg px-3 py-2">
        <div className="flex items-baseline gap-2 overflow-hidden">
          <h2 className="shrink-0 text-sm font-semibold text-tg-text">🏆 Лента</h2>
          <span className="min-w-0 flex-1 truncate text-[11px] text-tg-hint">
            Кто что открыл и с кем что случилось.
          </span>
        </div>
        <div className="mt-2 flex items-center gap-1.5">
          <ScopeButton
            active={scope === "all"}
            onClick={() => setScope("all")}
            label="Все события"
          />
          <ScopeButton
            active={scope === "mine"}
            onClick={() => setScope("mine")}
            label="Только мои"
          />
          <div className="ml-auto flex items-center gap-1.5">
            <TopToggle
              active={showFilters}
              onClick={() => {
                haptic("selection");
                setShowFilters((v) => !v);
              }}
              label={`🎚 Фильтры${kinds.size > 0 ? ` · ${kinds.size}` : ""}`}
              open={showFilters}
            />
            <TopToggle
              active={showActions}
              onClick={() => {
                haptic("selection");
                setShowActions((v) => !v);
              }}
              label="⚡ Действие"
              open={showActions}
            />
          </div>
        </div>
      </div>

      {/* Э21: фильтр по типу записи — чипы. Пусто = все типы. Свёрнут по клику. */}
      {showFilters && (
        <div className="flex flex-wrap gap-1.5 border-b border-tg-secondary-bg px-3 py-2">
          <KindChip
            active={kinds.size === 0}
            onClick={() => {
              if (kinds.size === 0) return;
              haptic("selection");
              setKinds(new Set());
            }}
            label="Все"
          />
          {availableKinds.map((k) => {
            const meta = FEED_KIND_LABELS[k] ?? { icon: "📌", title: k };
            return (
              <KindChip
                key={k}
                active={kinds.has(k)}
                onClick={() => toggleKind(k)}
                label={`${meta.icon} ${meta.title}`}
              />
            );
          })}
        </div>
      )}

      {/* GHG11: панель действий — инициировать механики прямо из ленты. В режиме
          «только апп» их отклик уезжает в ленту, в чат бот молчит. */}
      {showActions && <FeedActions onDone={() => setShowActions(false)} />}

      {/* Шиты календаря, переиспользуемые кнопкой действия. */}
      {showAuto && <AutoPickSheet />}
      {showLoser && <LoserSheet />}
      {showPoll && <PollSheet users={[]} />}

      {first && !first.enabled && (
        <div className="p-6 text-center text-sm text-tg-hint">
          Игра выключена — лента пока пуста.
        </div>
      )}

      {first?.enabled && items.length === 0 && (
        <div className="p-6 text-center text-sm text-tg-hint">
          {scope === "mine"
            ? "Ты пока ничего не открыл — заходи почаще."
            : "Тут пока тихо. Как только что-то случится — появится здесь."}
        </div>
      )}

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {/* Э21: активности прямо в приложении — вопросы и голосовое задание. */}
        {scope === "all" && <ActivitiesPanel />}
        {items.map((it) => (
          <FeedRow
            key={it.id}
            item={it}
            meId={meId}
            onOpenUser={(uid) => {
              haptic("light");
              openGuest(uid);
            }}
          />
        ))}

        {q.hasNextPage && (
          <button
            type="button"
            onClick={() => q.fetchNextPage()}
            disabled={q.isFetchingNextPage}
            className="w-full rounded-xl bg-tg-secondary-bg/70 py-2.5 text-sm font-medium text-tg-text active:scale-[0.99] disabled:opacity-60"
          >
            {q.isFetchingNextPage ? "Грузим…" : "Показать ещё"}
          </button>
        )}
      </div>
    </div>
  );
}

function ScopeButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={() => {
        if (active) return;
        haptic("selection");
        onClick();
      }}
      className={[
        "rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
        active
          ? "bg-tg-link text-white"
          : "bg-tg-secondary-bg/70 text-tg-hint",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

/** Э21: чип фильтра по типу (мультивыбор). */
function KindChip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
        active
          ? "bg-tg-link/15 text-tg-link ring-1 ring-tg-link/50"
          : "bg-tg-secondary-bg/70 text-tg-hint",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

/** GHG11: компактная кнопка-переключатель в шапке ленты (Фильтры/Действие). */
function TopToggle({
  active,
  onClick,
  label,
  open,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  open: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      className={[
        "rounded-full px-2.5 py-1.5 text-[11px] font-medium transition-colors",
        active
          ? "bg-tg-link text-white"
          : "bg-tg-secondary-bg/70 text-tg-text",
      ].join(" ")}
    >
      {label} <span aria-hidden>{open ? "▴" : "▾"}</span>
    </button>
  );
}

/**
 * GHG11: панель действий в ленте.
 *
 * Даёт инициировать механики, не уходя на календарь: авто-подбор, опрос,
 * автолох и (админам) прогон фразы. Шиты — те же, что в календаре, поэтому
 * поведение и результат совпадают. В режиме «только мини-апп» отклик бота
 * приходит в ленту, а не в чат.
 */
function FeedActions({ onDone }: { onDone: () => void }) {
  const setAuto = useUI((s) => s.setShowAutoPickSheet);
  const setPoll = useUI((s) => s.setShowPollSheet);
  const setLoser = useUI((s) => s.setShowLoserSheet);
  const meQ = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 5 * 60 * 1000 });
  const isAdmin = !!meQ.data?.is_admin;

  const phrases = useMutation({
    mutationFn: triggerRandomPhrases,
    onSuccess: () => {
      haptic("success");
      void showAlert("Прогон фраз запущен.");
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const open = (fn: () => void) => () => {
    haptic("light");
    fn();
    onDone();
  };

  return (
    <div className="flex flex-wrap gap-1.5 border-b border-tg-secondary-bg bg-tg-secondary-bg/20 px-3 py-2">
      <ActionChip onClick={open(() => setAuto(true))} label="🎯 Авто-подбор" />
      <ActionChip onClick={open(() => setPoll(true))} label="📊 Опрос" />
      <ActionChip onClick={open(() => setLoser(true))} label="🤡 Автолох" />
      {isAdmin && (
        <ActionChip
          onClick={() => {
            haptic("light");
            phrases.mutate();
          }}
          label="🗯 Прогон фразы"
        />
      )}
    </div>
  );
}

function ActionChip({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-lg bg-tg-secondary-bg/80 px-2.5 py-1.5 text-[11px] font-medium text-tg-text active:scale-[0.97]"
    >
      {label}
    </button>
  );
}

/** Э22: типы, которые раскрываются в подробности по тапу. */
const EXPANDABLE_KINDS = new Set([
  "achievement",
  "loser",
  "chukhan",
  "voice",
  "music",
  "music_game",
]);

function FeedRow({
  item,
  onOpenUser,
}: {
  item: FeedItem;
  meId: number;
  onOpenUser: (userId: number) => void;
}) {
  const when = formatWhen(item.at);
  const clickable = item.user_id !== null && item.user_id !== undefined;
  const [open, setOpen] = useState(false);
  const expandable = EXPANDABLE_KINDS.has(item.kind);
  // Музыка и голосовые — «плеер»: сворачиваем ОТДЕЛЬНОЙ кнопкой, чтобы тап
  // по треку/аудио не закрывал панель во время прослушивания.
  const playerLike = item.kind === "music" || item.kind === "voice";

  const toggle = () => {
    if (!expandable || playerLike) return;
    haptic("light");
    setOpen((o) => !o);
  };

  return (
    <div
      onClick={toggle}
      className={[
        "rounded-2xl bg-tg-secondary-bg/50 p-3",
        expandable && !playerLike ? "cursor-pointer active:scale-[0.99]" : "",
      ].join(" ")}
    >
      <div className="flex items-start gap-3">
        <div className="relative shrink-0">
          {item.avatar_url ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                if (clickable) onOpenUser(item.user_id!);
              }}
              className="block h-10 w-10 overflow-hidden rounded-full"
            >
              <img src={item.avatar_url} alt="" className="h-full w-full object-cover" />
            </button>
          ) : (
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-tg-secondary-bg text-lg">
              {item.icon}
            </div>
          )}
          {/* GHG11: плашки званий над головой — сегодня лох/чухан/червь. */}
          {(item.badges?.length ?? 0) > 0 && (
            <span className="pointer-events-none absolute -right-1 -top-1 text-[11px] leading-none [filter:drop-shadow(0_1px_1px_rgba(0,0,0,0.35))]">
              {item.badges!.join("")}
            </span>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-xs text-tg-hint">
            <span>{item.icon}</span>
            <span className="font-medium">{item.title}</span>
            <span className="ml-auto shrink-0">{when}</span>
            {expandable && (
              <span className="shrink-0 text-tg-hint">
                {playerLike ? "▸" : open ? "▾" : "▸"}
              </span>
            )}
          </div>
          {item.user_name && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                if (clickable) onOpenUser(item.user_id!);
              }}
              className="mt-0.5 block truncate text-sm font-medium text-tg-text"
            >
              {item.user_name}
            </button>
          )}
          {item.text && (
            <div
              className="mt-0.5 text-sm text-tg-hint [word-break:break-word]"
              // Тексты анонсов приходят с HTML-разметкой (<b>/<i>), как в чате.
              dangerouslySetInnerHTML={{ __html: item.text }}
            />
          )}
          {expandable && playerLike && !open && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                haptic("light");
                setOpen(true);
              }}
              className="mt-1 rounded-lg bg-tg-secondary-bg/80 px-2 py-1 text-[11px] font-medium text-tg-text"
            >
              {item.kind === "music" ? "🎧 Слушать и лайкать" : "🎙 Подробности и прослушать"}
            </button>
          )}
        </div>
      </div>

      {expandable && open && (
        <div className="mt-2 border-t border-tg-hint/15 pt-2">
          <FeedDetailPanel
            item={item}
            playerLike={playerLike}
            onClose={() => setOpen(false)}
          />
        </div>
      )}
    </div>
  );
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) {
    return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

/** Полная дата+время — «Серёга получил в 14:23, 3 октября» (Э22). */
function formatFull(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

// ---------------------------------------------------------------------------
// Э22: раскрывающиеся подробности записи ленты
// ---------------------------------------------------------------------------

function FeedDetailPanel({
  item,
  playerLike,
  onClose,
}: {
  item: FeedItem;
  playerLike: boolean;
  onClose: () => void;
}) {
  const d: FeedDetail = item.detail ?? {};
  return (
    <div className="space-y-1.5">
      {item.kind === "achievement" && (
        <>
          {d.description && (
            <div className="text-xs text-tg-text">
              <span className="text-tg-hint">За что: </span>
              {d.description}
            </div>
          )}
          <div className="text-[11px] text-tg-hint">
            {item.user_name ? `${item.user_name} получил: ` : "Получено: "}
            {formatFull(item.at)}
          </div>
          {typeof d.points === "number" && (
            <div className="text-[11px] text-tg-hint">Награда: +{d.points} XP</div>
          )}
        </>
      )}

      {item.kind === "voice" && (
        <>
          {d.condition && (
            <div className="text-xs text-tg-text">
              <span className="text-tg-hint">Условие: </span>
              {d.condition}
            </div>
          )}
          <div className="text-[11px] text-tg-hint">Открыто: {formatFull(d.opened_at)}</div>
          <div className="text-[11px] text-tg-hint">
            {d.closed
              ? `Закрыто: ${formatFull(d.closed_at)}`
              : `Идёт приём до: ${formatFull(d.expires_at)}`}
          </div>
          {typeof d.reward === "number" && (
            <div className="text-[11px] text-tg-hint">Награда: +{d.reward} XP</div>
          )}
          {(d.submissions?.length ?? 0) > 0 ? (
            <div className="space-y-1">
              {d.submissions!.map((s) => (
                <SubmissionPlayer key={s.id} submission={s} />
              ))}
            </div>
          ) : (
            <div className="text-[11px] text-tg-hint">Сдач не было.</div>
          )}
        </>
      )}

      {item.kind === "music" && <MusicDetail d={d} />}

      {item.kind === "music_game" && (
        <div className="text-[11px] text-tg-hint">
          {d.closed ? `Раунд закрыт: ${formatFull(d.closed_at)}` : "Голосование ещё идёт"}
        </div>
      )}

      {(item.kind === "loser" || item.kind === "chukhan") && (
        <div className="text-[11px] text-tg-hint">
          Когда: {formatFull(item.at)}
          {item.kind === "chukhan" && d.week_start
            ? ` · неделя с ${formatDate(d.week_start)}`
            : ""}
        </div>
      )}

      {playerLike && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            haptic("light");
            onClose();
          }}
          className="w-full rounded-lg bg-tg-secondary-bg/70 py-1.5 text-xs font-medium text-tg-text active:scale-[0.99]"
        >
          ▲ Свернуть
        </button>
      )}
    </div>
  );
}

/** Проигрыватель одной сдачи: аудио тянется блобом (нужен Authorization). */
function SubmissionPlayer({
  submission,
}: {
  submission: NonNullable<FeedDetail["submissions"]>[number];
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const play = async (e: MouseEvent) => {
    e.stopPropagation();
    haptic("light");
    if (url) {
      URL.revokeObjectURL(url);
      setUrl(null);
      return;
    }
    setLoading(true);
    try {
      setUrl(await fetchVoiceAudioUrl(submission.id));
    } catch {
      haptic("error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="flex items-center gap-2 rounded-lg bg-tg-bg/50 px-2 py-1.5"
    >
      <button
        type="button"
        onClick={play}
        disabled={loading}
        className="shrink-0 rounded-full bg-tg-secondary-bg px-2 py-1 text-sm disabled:opacity-50"
        aria-label="Прослушать"
      >
        {loading ? "…" : url ? "⏸" : "▶️"}
      </button>
      <span className="min-w-0 flex-1 truncate text-sm">
        {submission.user_name ?? "участник"}
      </span>
      {submission.duration != null && (
        <span className="shrink-0 text-xs tabular-nums text-tg-hint">
          {submission.duration}с
        </span>
      )}
      {url && (
        <audio
          src={url}
          autoPlay
          onEnded={() => {
            URL.revokeObjectURL(url);
            setUrl(null);
          }}
        />
      )}
    </div>
  );
}

function MusicDetail({ d }: { d: FeedDetail }) {
  const tracks = d.tracks ?? [];
  if (tracks.length === 0) {
    return <div className="text-[11px] text-tg-hint">Треков нет.</div>;
  }
  return (
    <div className="space-y-1">
      {tracks.map((t) => (
        <MusicTrackRow key={t.id} track={t} />
      ))}
    </div>
  );
}

function MusicTrackRow({
  track,
}: {
  track: NonNullable<FeedDetail["tracks"]>[number];
}) {
  const qc = useQueryClient();
  const like = useMutation({
    mutationFn: () => likeMusicTrack(track.id),
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["game-feed"] });
    },
    onError: () => haptic("error"),
  });
  const liked = like.data?.liked ?? track.liked;
  const likes = like.data?.likes ?? track.likes;

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="flex items-center gap-2 rounded-lg bg-tg-bg/50 px-2 py-1.5"
    >
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-tg-text">
          {track.title || track.performer || "трек"}
        </div>
        {track.performer && track.title && (
          <div className="truncate text-[11px] text-tg-hint">{track.performer}</div>
        )}
      </div>
      {track.url && (
        <a
          href={track.url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="shrink-0 rounded-full bg-tg-secondary-bg px-2 py-1 text-xs"
          aria-label="Открыть трек"
        >
          ▶️
        </a>
      )}
      <button
        type="button"
        disabled={like.isPending}
        onClick={(e) => {
          e.stopPropagation();
          haptic("light");
          like.mutate();
        }}
        className={[
          "shrink-0 rounded-full px-2 py-1 text-xs disabled:opacity-60",
          liked ? "bg-status-busy/20 text-status-busy" : "bg-tg-secondary-bg text-tg-hint",
        ].join(" ")}
      >
        {liked ? "❤️" : "🤍"} {likes}
      </button>
    </div>
  );
}
