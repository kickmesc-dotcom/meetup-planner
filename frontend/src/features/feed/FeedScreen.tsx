import { useEffect, useRef, useState, type MouseEvent } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  askAdvice,
  deleteFeedItem,
  fetchFeed,
  fetchVoiceAudioUrl,
  fetchWorm,
  hideFeedItem,
  likeMusicTrack,
  restoreFeedItem,
  runPhrase,
  transferWorm,
  unhideFeedItem,
  FEED_KIND_LABELS,
  type FeedDetail,
  type FeedItem,
} from "@/api/game";
import ActivitiesPanel from "./ActivitiesPanel";
import NominationsSheet from "./NominationsSheet";
import VoiceLikeButton from "./VoiceLikeButton";
import LoserSheet from "@/features/actions/LoserSheet";
import { Spinner } from "@/components/Spinner";
import ErrorState from "@/components/ErrorState";
import { useUI } from "@/store/ui";
import { haptic, showAlert } from "@/tg/webapp";
import { fetchMe, fetchUsers } from "@/api/availability";
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
  const [showNominations, setShowNominations] = useState(false);
  const openGuest = useUI((s) => s.openGuest);
  const showLoser = useUI((s) => s.showLoserSheet);
  // GHG11(4): переход из анонса фичи — раскрываем панель «Действия».
  const feedAnchor = useUI((s) => s.feedAnchor);
  const setFeedAnchor = useUI((s) => s.setFeedAnchor);
  useEffect(() => {
    if (feedAnchor === "feed-actions") {
      setShowActions(true);
      setFeedAnchor(null);
    }
  }, [feedAnchor, setFeedAnchor]);
  const kindsParam = [...kinds].sort().join(",");

  const qc = useQueryClient();
  const meQ = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 5 * 60 * 1000 });
  const isAdmin = !!meQ.data?.is_admin;

  // GHG11: плашка-отмена после удаления/скрытия записи. Держимся ~4.5 сек —
  // этого хватает, чтобы передумать, но запись не «залипает» в ленте.
  const [toast, setToast] = useState<{
    text: string;
    undo?: () => Promise<unknown> | unknown;
  } | null>(null);
  const toastTimer = useRef<number | null>(null);
  const dismissToast = () => {
    if (toastTimer.current !== null) {
      window.clearTimeout(toastTimer.current);
      toastTimer.current = null;
    }
    setToast(null);
  };
  const showToast = (text: string, undo?: () => Promise<unknown> | unknown) => {
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    setToast({ text, undo });
    toastTimer.current = window.setTimeout(() => {
      toastTimer.current = null;
      setToast(null);
    }, 4500);
  };
  useEffect(
    () => () => {
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  const invalidateFeed = () => qc.invalidateQueries({ queryKey: ["game-feed"] });

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
  // GHG11(4): новый компактный вид по умолчанию; "classic" — старый.
  const compact = first?.feed_view !== "classic";

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
        <div className="flex items-center gap-1.5">
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
              label={kinds.size > 0 ? `Фильтры · ${kinds.size}` : "Фильтры"}
              open={showFilters}
            />
            <TopToggle
              active={showActions}
              onClick={() => {
                haptic("selection");
                setShowActions((v) => !v);
              }}
              label="Действия"
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
      {showActions && (
        <FeedActions
          onDone={() => setShowActions(false)}
          onOpenNominations={() => {
            haptic("light");
            setShowActions(false);
            setShowNominations(true);
          }}
        />
      )}

      {/* Шит автолоха (свой, гейтится по рангу). */}
      {showLoser && <LoserSheet />}
      {showNominations && <NominationsSheet onClose={() => setShowNominations(false)} />}

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
            isAdmin={isAdmin}
            compact={compact}
            onOpenUser={(uid) => {
              haptic("light");
              openGuest(uid);
            }}
            onModerated={showToast}
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

      {/* GHG11: плашка-отмена поверх ленты. */}
      {toast && (
        <div className="pointer-events-none fixed inset-x-0 bottom-20 z-40 flex justify-center px-4">
          <div className="pointer-events-auto flex items-center gap-3 rounded-xl bg-tg-secondary-bg px-3 py-2 shadow-lg">
            <span className="text-xs text-tg-text">{toast.text}</span>
            {toast.undo && (
              <button
                type="button"
                onClick={async () => {
                  haptic("medium");
                  const undo = toast.undo!;
                  dismissToast();
                  try {
                    await undo();
                  } catch {
                    haptic("error");
                  }
                  void invalidateFeed();
                }}
                className="shrink-0 rounded-lg bg-tg-link/15 px-2.5 py-1 text-xs font-semibold text-tg-link"
              >
                Отменить
              </button>
            )}
          </div>
        </div>
      )}
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

/** GHG11: компактная кнопка-переключатель в шапке ленты (Фильтры/Действия). */
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
        "inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-[11px] font-medium transition-colors",
        active ? "bg-tg-link text-white" : "bg-tg-secondary-bg/70 text-tg-text",
      ].join(" ")}
    >
      {label}
      <svg
        aria-hidden
        viewBox="0 0 12 12"
        className={[
          "h-2.5 w-2.5 transition-transform",
          open ? "rotate-180" : "",
        ].join(" ")}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M2.5 4.5 6 8l3.5-3.5" />
      </svg>
    </button>
  );
}

/**
 * GHG11: панель действий в ленте.
 *
 * Даёт инициировать механики, не уходя на календарь: магический шар (совет),
 * автолох, номинации/голосование и (для владельца червя) передачу червя.
 * Админам — прогон фразы. В режиме «только мини-апп» отклик бота приходит в
 * ленту, а не в чат.
 */
function FeedActions({
  onDone,
  onOpenNominations,
}: {
  onDone: () => void;
  onOpenNominations: () => void;
}) {
  const qc = useQueryClient();
  const setLoser = useUI((s) => s.setShowLoserSheet);
  const meQ = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 5 * 60 * 1000 });
  const isAdmin = !!meQ.data?.is_admin;

  const wormQ = useQuery({ queryKey: ["worm"], queryFn: fetchWorm, staleTime: 30_000 });

  // GHG11(3): сценарий шара — вопрос (необязательно) + куда положить результат.
  const [showAdvice, setShowAdvice] = useState(false);
  const [question, setQuestion] = useState("");
  const [adviceTarget, setAdviceTarget] = useState<"feed" | "header">("feed");

  const phrases = useMutation({
    mutationFn: runPhrase,
    onSuccess: (res) => {
      if (res.ok) {
        haptic("success");
        // GHG11(3): фраза уже в ленте — просто обновляем её, без плашки.
        qc.invalidateQueries({ queryKey: ["game-feed"] });
      } else {
        haptic("error");
      }
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const advice = useMutation({
    mutationFn: () => askAdvice(question, adviceTarget),
    onSuccess: (res) => {
      if (res.ok) {
        haptic("success");
        setQuestion("");
        if (adviceTarget === "feed") {
          qc.invalidateQueries({ queryKey: ["game-feed"] });
        }
      } else {
        haptic("error");
        if (res.status === "disabled") void showAlert("Магический шар выключен в настройках.");
        else if (res.status === "empty") void showAlert("Пул советов пуст.");
      }
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

  const ownerName = wormQ.data?.owner_name;
  const isWormOwner = wormQ.data?.is_owner === true;

  return (
    <div
      id="feed-actions"
      className="border-b border-tg-secondary-bg bg-tg-secondary-bg/20 px-3 py-2"
    >
      <div className="flex flex-wrap gap-1.5">
        <ActionChip
          onClick={() => {
            haptic("light");
            setShowAdvice((v) => !v);
          }}
          label="🔮 Магический шар"
        />
        <ActionChip onClick={open(() => setLoser(true))} label="🤡 Автолох" />
        <ActionChip onClick={onOpenNominations} label="🎮 Номинации" />
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

      {/* GHG11(3): сценарий шара — вопрос + радио «в ленту / в шапку». */}
      {showAdvice && (
        <div className="mt-2 space-y-2 rounded-xl bg-tg-bg/60 px-3 py-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Вопрос шару (необязательно)"
            maxLength={500}
            className="w-full rounded-lg bg-tg-secondary-bg px-2 py-1.5 text-sm text-tg-text outline-none"
          />
          <div className="flex gap-1.5">
            <TargetRadio
              active={adviceTarget === "feed"}
              onClick={() => setAdviceTarget("feed")}
              label="🔮 В ленту"
            />
            <TargetRadio
              active={adviceTarget === "header"}
              onClick={() => setAdviceTarget("header")}
              label="📌 В шапку"
            />
          </div>
          <button
            type="button"
            disabled={advice.isPending}
            onClick={() => {
              haptic("medium");
              advice.mutate();
            }}
            className="w-full rounded-lg bg-tg-button px-3 py-1.5 text-sm font-medium text-tg-button-text disabled:opacity-50"
          >
            {advice.isPending ? "Крутим…" : "Закрутить шар"}
          </button>
          {adviceTarget === "header" && advice.data?.ok && advice.data.text && (
            <div className="rounded-lg bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text">
              <span className="mr-1">🔮</span>
              {advice.data.text}
            </div>
          )}
        </div>
      )}

      {/* GHG11: действия червя доступны только его владельцу. */}
      {isWormOwner && (
        <div className="mt-2 rounded-xl bg-tg-bg/60 px-3 py-2">
          <div className="text-[11px] text-tg-hint">
            🪱 Ты — червь-господин{ownerName ? ` (${ownerName})` : ""}. Передай власть:
          </div>
          <WormTransfer />
        </div>
      )}
    </div>
  );
}

function WormTransfer() {
  const qc = useQueryClient();
  const usersQ = useQuery({ queryKey: ["users"], queryFn: fetchUsers, staleTime: 60_000 });
  const meQ = useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 5 * 60 * 1000 });
  const [target, setTarget] = useState<string>("");
  const users = (usersQ.data ?? []).filter((u) => u.id !== meQ.data?.id);

  const mut = useMutation({
    mutationFn: (userId: number) => transferWorm(userId),
    onSuccess: (res) => {
      if (res.ok) {
        haptic("success");
        void showAlert("Червь передан.");
        setTarget("");
      } else {
        haptic("error");
        void showAlert(transferStatusText(res.status));
      }
      void qc.invalidateQueries({ queryKey: ["worm"] });
      void qc.invalidateQueries({ queryKey: ["game-feed"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  return (
    <div className="mt-1.5 flex gap-1.5">
      <select
        value={target}
        onChange={(e) => setTarget(e.target.value)}
        className="min-w-0 flex-1 rounded-lg bg-tg-secondary-bg px-2 py-1.5 text-sm"
      >
        <option value="">Кому передать…</option>
        {users.map((u) => (
          <option key={u.id} value={u.id}>
            {u.display_name}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={!target || mut.isPending}
        onClick={() => {
          haptic("medium");
          mut.mutate(Number(target));
        }}
        className="shrink-0 rounded-lg bg-tg-button px-3 py-1.5 text-sm font-medium text-tg-button-text disabled:opacity-50"
      >
        {mut.isPending ? "…" : "Передать"}
      </button>
    </div>
  );
}

function transferStatusText(status: string): string {
  switch (status) {
    case "not_owner":
      return "Ты больше не владелец червя.";
    case "unknown_user":
      return "Участник не найден.";
    case "self":
      return "Нельзя передать червя самому себе.";
    case "same":
      return "Этот участник и так червь-господин.";
    default:
      return "Не получилось передать червя.";
  }
}

/** GHG11(3): радиокнопка «куда положить результат шара». */
function TargetRadio({
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
        haptic("selection");
        onClick();
      }}
      className={[
        "flex-1 rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-colors",
        active ? "bg-tg-link text-white" : "bg-tg-secondary-bg/80 text-tg-hint",
      ].join(" ")}
    >
      {active ? "◉ " : "◯ "}
      {label}
    </button>
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
  isAdmin,
  onOpenUser,
  onModerated,
  compact,
}: {
  item: FeedItem;
  meId: number;
  isAdmin: boolean;
  onOpenUser: (userId: number) => void;
  onModerated: (text: string, undo?: () => Promise<unknown> | unknown) => void;
  /** GHG11(4): новый компактный вид — миниатюры участников под заданием. */
  compact: boolean;
}) {
  const when = formatWhen(item.at);
  const clickable = item.user_id !== null && item.user_id !== undefined;
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  // GHG11(4): факт тапа по миниатюре — какую сдачу включить при раскрытии.
  const [playId, setPlayId] = useState<number | null>(null);
  const voiceSubs = item.kind === "voice" ? item.detail?.submissions ?? [] : [];
  const qc = useQueryClient();
  const expandable = EXPANDABLE_KINDS.has(item.kind);
  // Музыка и голосовые — «плеер»: сворачиваем ОТДЕЛЬНОЙ кнопкой, чтобы тап
  // по треку/аудио не закрывал панель во время прослушивания.
  const playerLike = item.kind === "music" || item.kind === "voice";

  const invalidateFeed = () => qc.invalidateQueries({ queryKey: ["game-feed"] });

  const hide = useMutation({
    mutationFn: () => hideFeedItem(item.id),
    onSuccess: () => {
      haptic("medium");
      setMenu(false);
      void invalidateFeed();
      onModerated("Запись скрыта у тебя", () => unhideFeedItem(item.id));
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const remove = useMutation({
    mutationFn: () => deleteFeedItem(item.id),
    onSuccess: (res) => {
      haptic("medium");
      setMenu(false);
      void invalidateFeed();
      if (res?.hard) {
        // GHG11(3): источник стёрт из БД — откатывать нечего.
        onModerated("Запись удалена из базы");
      } else {
        onModerated("Запись удалена из ленты", () => restoreFeedItem(item.id));
      }
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

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
            <button
              type="button"
              aria-label="Действия с записью"
              onClick={(e) => {
                e.stopPropagation();
                haptic("selection");
                setMenu((m) => !m);
              }}
              className="shrink-0 rounded-md px-1 text-base leading-none text-tg-hint"
            >
              👁
            </button>
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
          {/* GHG11(4): новый вид — компактно, без раскрытия: кто сдал и сколько XP. */}
          {compact && voiceSubs.length > 0 && (
            <ParticipantsStrip
              submissions={voiceSubs}
              reward={item.detail?.reward}
              onPlay={(id) => {
                haptic("light");
                setPlayId(id);
                setOpen(true);
              }}
            />
          )}
          {expandable && playerLike && !open && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                haptic("light");
                setPlayId(null);
                setOpen(true);
              }}
              className="mt-1 rounded-lg bg-tg-secondary-bg/80 px-2 py-1 text-[11px] font-medium text-tg-text"
            >
              {item.kind === "music" ? "🎧 Слушать и лайкать" : "🎙 Подробности и прослушать"}
            </button>
          )}

          {/* GHG11: модерация — «скрыть у себя» всем, «удалить» админу. */}
          {menu && (
            <div
              onClick={(e) => e.stopPropagation()}
              className="mt-2 flex flex-wrap gap-1.5"
            >
              <button
                type="button"
                disabled={hide.isPending}
                onClick={() => hide.mutate()}
                className="rounded-lg bg-tg-secondary-bg px-2.5 py-1 text-[11px] font-medium text-tg-text disabled:opacity-50"
              >
                🙈 Скрыть у себя
              </button>
              {isAdmin && (
                <button
                  type="button"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate()}
                  className="rounded-lg bg-status-busy/15 px-2.5 py-1 text-[11px] font-medium text-status-busy disabled:opacity-50"
                >
                  🗑 Удалить
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {expandable && open && (
        <div className="mt-2 border-t border-tg-hint/15 pt-2">
          <FeedDetailPanel
            item={item}
            playerLike={playerLike}
            compact={compact}
            autoPlayId={playId}
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
  compact,
  autoPlayId,
  onClose,
}: {
  item: FeedItem;
  playerLike: boolean;
  compact: boolean;
  autoPlayId?: number | null;
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
              {/* GHG11(4): текст задания приходит с HTML-разметкой (<b>/<i>),
                  как в чате, — рендерим её, а не показываем теги текстом. */}
              <span
                className="[word-break:break-word]"
                dangerouslySetInnerHTML={{ __html: d.condition }}
              />
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
                <SubmissionPlayer
                  key={s.id}
                  submission={s}
                  reward={d.reward}
                  autoPlay={autoPlayId === s.id}
                  compact={compact}
                />
              ))}
            </div>
          ) : (
            <div className="text-[11px] text-tg-hint">
              Никто не отправил свой вариант.
            </div>
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

/**
 * GHG11(4): компактный ряд миниатюр участников голосового задания.
 *
 * В новом виде ленты под блоком задания сразу видно, кто принял участие и
 * сколько XP получил за вариант, — без раскрытия и без «спама отдельными
 * блоками». Тап по миниатюре открывает запись и включает этот вариант.
 */
function ParticipantsStrip({
  submissions,
  reward,
  onPlay,
}: {
  submissions: NonNullable<FeedDetail["submissions"]>;
  reward?: number;
  onPlay: (id: number) => void;
}) {
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {submissions.map((s) => {
        const xp = s.xp ?? reward;
        return (
          <button
            key={s.id}
            type="button"
            title={s.user_name ?? "участник"}
            onClick={(e) => {
              e.stopPropagation();
              onPlay(s.id);
            }}
            className="relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-full bg-tg-secondary-bg text-xs font-semibold text-tg-text ring-1 ring-tg-hint/20"
          >
            {s.avatar_url ? (
              <img src={s.avatar_url} alt="" className="h-full w-full object-cover" />
            ) : (
              (s.user_name ?? "?").slice(0, 1).toUpperCase()
            )}
            {typeof xp === "number" && xp > 0 && (
              <span className="absolute -bottom-0.5 -right-0.5 rounded-full bg-status-free px-1 text-[9px] font-bold leading-tight text-white">
                +{xp}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Проигрыватель одной сдачи: аудио тянется блобом (нужен Authorization). */
function SubmissionPlayer({
  submission,
  reward,
  autoPlay = false,
  compact = false,
}: {
  submission: NonNullable<FeedDetail["submissions"]>[number];
  reward?: number;
  autoPlay?: boolean;
  compact?: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setUrl(await fetchVoiceAudioUrl(submission.id));
    } catch {
      haptic("error");
    } finally {
      setLoading(false);
    }
  };

  const play = async (e: MouseEvent) => {
    e.stopPropagation();
    haptic("light");
    if (url) {
      URL.revokeObjectURL(url);
      setUrl(null);
      return;
    }
    await load();
  };

  // GHG11(4): тап по миниатюре в новом виде сразу включает эту сдачу.
  useEffect(() => {
    if (autoPlay) void load();
    // Загружаем один раз — на монтирование с флагом авто-проигрывания.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPlay]);

  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );

  const xp = submission.xp ?? reward;

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className={[
        "flex items-center gap-2 rounded-lg bg-tg-bg/50 px-2 py-1.5",
        compact && autoPlay ? "ring-1 ring-tg-link/40" : "",
      ].join(" ")}
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
        {typeof xp === "number" && xp > 0 && (
          <span className="ml-1.5 text-[11px] font-medium text-status-free">
            +{xp} XP
          </span>
        )}
      </span>
      {submission.duration != null && (
        <span className="shrink-0 text-xs tabular-nums text-tg-hint">
          {submission.duration}с
        </span>
      )}
      <VoiceLikeButton
        submissionId={submission.id}
        initialLiked={submission.liked ?? false}
        initialLikes={submission.likes ?? 0}
        invalidateKey="game-feed"
      />
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
