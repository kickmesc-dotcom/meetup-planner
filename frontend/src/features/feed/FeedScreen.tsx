import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { fetchFeed, FEED_KIND_LABELS, type FeedItem } from "@/api/game";
import { Spinner } from "@/components/Spinner";
import ErrorState from "@/components/ErrorState";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";

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
  const openGuest = useUI((s) => s.openGuest);
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
      <div className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <ScopeButton
          active={scope === "all"}
          onClick={() => setScope("all")}
          label="Все"
        />
        <ScopeButton
          active={scope === "mine"}
          onClick={() => setScope("mine")}
          label="Только мои"
        />
      </div>

      {/* Э21: фильтр по типу записи — чипы. Пусто = все типы. */}
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

  return (
    <div className="flex items-start gap-3 rounded-2xl bg-tg-secondary-bg/50 p-3">
      {item.avatar_url ? (
        <button
          type="button"
          onClick={() => clickable && onOpenUser(item.user_id!)}
          className="h-10 w-10 shrink-0 overflow-hidden rounded-full"
        >
          <img src={item.avatar_url} alt="" className="h-full w-full object-cover" />
        </button>
      ) : (
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-tg-secondary-bg text-lg">
          {item.icon}
        </div>
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-xs text-tg-hint">
          <span>{item.icon}</span>
          <span className="font-medium">{item.title}</span>
          <span className="ml-auto shrink-0">{when}</span>
        </div>
        {item.user_name && (
          <button
            type="button"
            onClick={() => clickable && onOpenUser(item.user_id!)}
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
      </div>
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
