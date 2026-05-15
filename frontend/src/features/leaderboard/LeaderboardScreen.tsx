import { useQuery } from "@tanstack/react-query";
import { fetchLoserStats } from "@/api/meetings";
import { fetchChukhanLeaderboard, type ChukhanLeaderRow } from "@/api/admin";
import type { User } from "@/types";
import { ListSkeleton } from "@/components/Skeleton";

interface Props {
  users: User[];
}

export default function LeaderboardScreen({ users }: Props) {
  const losers = useQuery({
    queryKey: ["loser", "stats"],
    queryFn: fetchLoserStats,
  });
  const chukhans = useQuery({
    queryKey: ["chukhan", "leaderboard"],
    queryFn: fetchChukhanLeaderboard,
  });

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      <Section
        title="💩 Топ чуханов"
        subtitle="Кому чаще всего выпадало звание чухана недели"
        rows={(chukhans.data ?? []).map((r) => ({ user_id: r.user_id, count: r.count }))}
        users={users}
        empty="Чуханов ещё не было."
        loading={chukhans.isPending}
      />
      <Section
        title="🎲 Топ лохов дня"
        subtitle="Сколько раз каждого выкатывало в лохи"
        rows={Object.entries(losers.data?.counts ?? {}).map(
          ([uid, cnt]) => ({ user_id: Number(uid), count: cnt }),
        )}
        users={users}
        empty="Никто ещё не попадался."
        loading={losers.isPending}
      />
    </div>
  );
}

function Section({
  title,
  subtitle,
  rows,
  users,
  empty,
  loading,
}: {
  title: string;
  subtitle: string;
  rows: ChukhanLeaderRow[];
  users: User[];
  empty: string;
  loading: boolean;
}) {
  const userById = Object.fromEntries(users.map((u) => [u.id, u] as const));
  const sorted = [...rows].sort((a, b) => b.count - a.count);
  const max = sorted[0]?.count ?? 1;

  return (
    <div className="rounded-xl bg-tg-secondary-bg/60 p-3">
      <div className="text-base font-semibold">{title}</div>
      <div className="text-xs text-tg-hint mb-2">{subtitle}</div>
      {loading ? (
        <ListSkeleton rows={4} />
      ) : sorted.length === 0 ? (
        <div className="text-xs text-tg-hint py-2">{empty}</div>
      ) : (
        <div className="space-y-1.5">
          {sorted.map((r, i) => {
            const u = userById[r.user_id];
            const ratio = (r.count / max) * 100;
            return (
              <div key={r.user_id} className="flex items-center gap-2">
                <div className="text-xs w-4 text-tg-hint text-right">{i + 1}</div>
                <div
                  className="w-7 h-7 rounded-full overflow-hidden flex items-center justify-center text-white text-xs font-medium shrink-0"
                  style={{ background: u?.color_hex ?? "#888" }}
                >
                  {u?.avatar_url ? (
                    <img src={u.avatar_url} alt="" className="w-full h-full object-cover" />
                  ) : (
                    (u?.display_name[0] ?? "?")
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate">
                    {u?.display_name ?? `id=${r.user_id}`}
                  </div>
                  <div className="h-1.5 rounded-full bg-tg-bg/50 mt-0.5 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-tg-link"
                      style={{ width: `${ratio}%` }}
                    />
                  </div>
                </div>
                <div className="text-sm font-semibold tabular-nums w-7 text-right">
                  {r.count}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
