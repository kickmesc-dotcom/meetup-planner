import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  fetchChukhanHistory,
  fetchGamesHistory,
  fetchLoserHistory,
  fetchPollsHistory,
  type PollHistoryRow,
} from "@/api/admin";
import type { User } from "@/types";
import { haptic } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";

interface Props {
  users: User[];
  onBack: () => void;
}

// GHG6 N1.3: добавлены вкладки «Опросы» и «Игры» — история опросов из БД.
type Tab = "chukhan" | "loser" | "polls" | "games";

export default function HistoryScreen({ users, onBack }: Props) {
  const [tab, setTab] = useState<Tab>("chukhan");

  const chukhanHistory = useQuery({
    queryKey: ["admin", "history"],
    queryFn: fetchChukhanHistory,
    enabled: tab === "chukhan",
  });
  const loserHistory = useQuery({
    queryKey: ["admin", "loser-history"],
    queryFn: fetchLoserHistory,
    enabled: tab === "loser",
  });
  const pollsHistory = useQuery({
    queryKey: ["admin", "polls-history"],
    queryFn: () => fetchPollsHistory(30),
    enabled: tab === "polls",
  });
  const gamesHistory = useQuery({
    queryKey: ["admin", "games-history"],
    queryFn: () => fetchGamesHistory(30),
    enabled: tab === "games",
  });

  const userById = Object.fromEntries(users.map((u) => [u.id, u] as const));

  return (
    <SubScreen
      title="📜 История"
      subtitle="Чуханы недели и лохи дня"
      onBack={onBack}
    >
      <div className="flex rounded-lg bg-tg-bg/40 p-1 gap-1 overflow-x-auto">
        <TabButton active={tab === "chukhan"} onClick={() => { haptic("selection"); setTab("chukhan"); }}>
          💩 Чуханы
        </TabButton>
        <TabButton active={tab === "loser"} onClick={() => { haptic("selection"); setTab("loser"); }}>
          🤡 Лохи
        </TabButton>
        <TabButton active={tab === "polls"} onClick={() => { haptic("selection"); setTab("polls"); }}>
          🗳 Опросы
        </TabButton>
        <TabButton active={tab === "games"} onClick={() => { haptic("selection"); setTab("games"); }}>
          🎮 Игры
        </TabButton>
      </div>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        {tab === "polls" || tab === "games" ? (
          <PollsHistoryList
            data={(tab === "polls" ? pollsHistory.data : gamesHistory.data) ?? []}
            isPending={(tab === "polls" ? pollsHistory.isPending : gamesHistory.isPending)}
          />
        ) : tab === "chukhan" ? (
          chukhanHistory.isPending ? (
            <ListSkeleton rows={5} />
          ) : (chukhanHistory.data ?? []).length === 0 ? (
            <div className="text-xs text-tg-hint">Пока пусто.</div>
          ) : (
            <div className="divide-y divide-tg-bg/40">
              {(chukhanHistory.data ?? []).map((h) => {
                const u = userById[h.user_id];
                return (
                  <div key={h.id} className="flex items-center gap-2 py-1.5">
                    <div className="text-xs text-tg-hint w-20">
                      {format(new Date(h.week_start), "dd.MM.yy")}
                    </div>
                    <div
                      className="w-6 h-6 rounded-full overflow-hidden inline-flex items-center justify-center text-white text-[10px]"
                      style={{ background: u?.color_hex ?? "#888" }}
                    >
                      {u?.avatar_url ? (
                        <img src={u.avatar_url} alt="" className="w-full h-full object-cover" />
                      ) : (
                        u?.display_name[0] ?? "?"
                      )}
                    </div>
                    <div className="flex-1 truncate text-sm text-tg-text">
                      {u?.display_name ?? `id=${h.user_id}`}
                    </div>
                    <div
                      className={[
                        "text-[10px] rounded-full px-1.5 py-0.5",
                        h.posted_at
                          ? "bg-status-free/15 text-status-free"
                          : "bg-status-maybe/15 text-status-maybe",
                      ].join(" ")}
                    >
                      {h.posted_at ? "запощен" : "ждёт"}
                    </div>
                  </div>
                );
              })}
            </div>
          )
        ) : loserHistory.isPending ? (
          <ListSkeleton rows={5} />
        ) : (loserHistory.data ?? []).length === 0 ? (
          <div className="text-xs text-tg-hint">Пока никто не пролетал.</div>
        ) : (
          <div className="divide-y divide-tg-bg/40">
            {(loserHistory.data ?? []).map((h) => {
              const u = userById[h.loser_user_id];
              return (
                <div key={h.id} className="flex items-start gap-2 py-1.5">
                  <div className="text-xs text-tg-hint w-20 shrink-0">
                    {format(new Date(h.rolled_at), "dd.MM HH:mm")}
                  </div>
                  <div
                    className="w-6 h-6 rounded-full overflow-hidden inline-flex items-center justify-center text-white text-[10px] shrink-0"
                    style={{ background: u?.color_hex ?? "#888" }}
                  >
                    {u?.avatar_url ? (
                      <img src={u.avatar_url} alt="" className="w-full h-full object-cover" />
                    ) : (
                      u?.display_name[0] ?? "?"
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-tg-text truncate">
                      {u?.display_name ?? `id=${h.loser_user_id}`}
                    </div>
                    {h.reason_text && (
                      <div className="text-[11px] text-tg-hint italic line-clamp-2">
                        «{h.reason_text}»
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </SubScreen>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "flex-1 min-h-9 min-w-[80px] rounded-md text-sm font-medium transition-colors px-2 whitespace-nowrap",
        active
          ? "bg-tg-button text-tg-button-text"
          : "bg-transparent text-tg-hint",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

/** GHG6 N1.3: рендер истории опросов / игр. Раскрытие — детали по опции. */
function PollsHistoryList({
  data,
  isPending,
}: {
  data: PollHistoryRow[];
  isPending: boolean;
}) {
  if (isPending) return <ListSkeleton rows={5} />;
  if (data.length === 0) {
    return <div className="text-xs text-tg-hint">Пока пусто.</div>;
  }
  return (
    <div className="space-y-2">
      {data.map((row) => (
        <PollHistoryItem key={row.poll_id} row={row} />
      ))}
    </div>
  );
}

function PollHistoryItem({ row }: { row: PollHistoryRow }) {
  const [open, setOpen] = useState(false);
  const totalVotes = row.options.reduce((sum, o) => sum + o.votes.length, 0);
  const kindLabel =
    row.kind === "game_choice"
      ? "🎮 во что"
      : row.kind === "game_when"
      ? "🕒 когда"
      : row.kind === "zaebal"
      ? "⏸ zaebal"
      : row.kind ?? "meetup";
  return (
    <div className="rounded-lg bg-tg-bg/50">
      <button
        type="button"
        onClick={() => {
          haptic("light");
          setOpen((v) => !v);
        }}
        className="w-full text-left px-2 py-1.5"
      >
        <div className="flex items-center gap-2">
          <div className="text-[10px] text-tg-hint shrink-0 w-20">
            {format(new Date(row.created_at), "dd.MM HH:mm")}
          </div>
          <div className="text-[10px] rounded-full px-1.5 py-0.5 shrink-0 bg-tg-link/15 text-tg-link">
            {kindLabel}
          </div>
          <div className="flex-1 text-sm text-tg-text truncate">{row.question}</div>
          <div className="text-[10px] text-tg-hint shrink-0">
            {totalVotes}🗳 {row.closed ? "✓" : "⏳"}
          </div>
        </div>
      </button>
      {open && (
        <div className="px-2 pb-2 space-y-1">
          {row.options.length === 0 ? (
            <div className="text-[11px] text-tg-hint">Опций нет.</div>
          ) : (
            row.options.map((opt) => (
              <div key={opt.id} className="rounded-md bg-tg-bg/70 px-2 py-1">
                <div className="flex items-center gap-2">
                  <div className="flex-1 text-xs text-tg-text truncate">
                    {opt.label ??
                      (opt.starts_at && opt.ends_at
                        ? `${format(new Date(opt.starts_at), "dd.MM HH:mm")}–${format(
                            new Date(opt.ends_at),
                            "HH:mm",
                          )}`
                        : "—")}
                  </div>
                  <div className="text-[10px] text-tg-hint shrink-0">
                    {opt.votes.length}🗳
                  </div>
                </div>
                {opt.votes.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {opt.votes.map((v) => (
                      <span
                        key={`${opt.id}-${v.user_id}`}
                        className="text-[10px] rounded-full bg-tg-secondary-bg/60 px-1.5 py-0.5 text-tg-text"
                        title={format(new Date(v.voted_at), "dd.MM HH:mm")}
                      >
                        {v.display_name ?? `id=${v.user_id}`}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
