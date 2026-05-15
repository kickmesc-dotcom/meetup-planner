import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { fetchChukhanHistory, fetchLoserHistory } from "@/api/admin";
import type { User } from "@/types";
import { haptic } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";

interface Props {
  users: User[];
  onBack: () => void;
}

type Tab = "chukhan" | "loser";

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

  const userById = Object.fromEntries(users.map((u) => [u.id, u] as const));

  return (
    <SubScreen
      title="📜 История"
      subtitle="Чуханы недели и лохи дня"
      onBack={onBack}
    >
      <div className="flex rounded-lg bg-tg-bg/40 p-1 gap-1">
        <TabButton active={tab === "chukhan"} onClick={() => { haptic("selection"); setTab("chukhan"); }}>
          💩 Чуханы
        </TabButton>
        <TabButton active={tab === "loser"} onClick={() => { haptic("selection"); setTab("loser"); }}>
          🤡 Лохи
        </TabButton>
      </div>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        {tab === "chukhan" ? (
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
        "flex-1 min-h-9 rounded-md text-sm font-medium transition-colors",
        active
          ? "bg-tg-button text-tg-button-text"
          : "bg-transparent text-tg-hint",
      ].join(" ")}
    >
      {children}
    </button>
  );
}
