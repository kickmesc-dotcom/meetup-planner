import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { ru } from "date-fns/locale";
import { motion } from "framer-motion";
import { fetchPolls, type Poll } from "@/api/meetings";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import type { User } from "@/types";

interface Props {
  users: User[];
  meId: number;
}

export default function PollsScreen({ users, meId }: Props) {
  const polls = useQuery({
    queryKey: ["polls"],
    queryFn: fetchPolls,
    staleTime: 15_000,
  });

  if (polls.isPending) {
    return <PollsSkeleton />;
  }
  if (polls.isError) {
    return <ErrorState error={polls.error} onRetry={() => polls.refetch()} />;
  }
  const list = polls.data ?? [];
  if (list.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-6 text-center">
        <Icon name="clipboard" size={34} className="mb-2 text-tg-hint" />
        <div className="text-tg-hint">Опросов пока не было.</div>
        <div className="text-xs text-tg-hint mt-2">
          Запусти из «Календаря»: авто-подбор → опрос — бот опубликует его в
          чате.
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3">
      {list.map((p) => (
        <PollCard key={p.id} poll={p} users={users} meId={meId} />
      ))}
    </div>
  );
}

function PollCard({
  poll,
  users,
  meId,
}: {
  poll: Poll;
  users: User[];
  meId: number;
}) {
  const usersById = new Map(users.map((u) => [u.id, u]));
  const totalVotes = poll.options.reduce((s, o) => s + o.voter_user_ids.length, 0);
  const closesAt = poll.closes_at ? new Date(poll.closes_at) : null;
  const isClosed = closesAt ? closesAt.getTime() < Date.now() : false;

  const sortedByStart = [...poll.options].sort(
    (a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
  );
  const maxVotes = Math.max(1, ...poll.options.map((o) => o.voter_user_ids.length));
  const winnerCount = Math.max(0, ...poll.options.map((o) => o.voter_user_ids.length));

  return (
    <motion.div
      initial={{ y: 8, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="rounded-card bg-tg-secondary-bg/60 p-3 shadow-sm"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-base font-semibold">{poll.question}</div>
          <div className="text-xs text-tg-hint mt-0.5">
            {totalVotes} {pluralVotes(totalVotes)}
            {closesAt && (
              <>
                {" · "}
                {isClosed
                  ? "закрыт"
                  : `до ${format(closesAt, "d MMM HH:mm", { locale: ru })}`}
              </>
            )}
          </div>
        </div>
        <div
          className={[
            "shrink-0 rounded-full px-2 py-0.5 text-2xs font-medium",
            isClosed
              ? "bg-tg-bg/60 text-tg-hint"
              : "bg-status-free/15 text-status-free",
          ].join(" ")}
        >
          {isClosed ? <Icon name="lock" size={12} /> : "идёт"}
        </div>
      </div>

      <div className="mt-3 space-y-1.5">
        {sortedByStart.map((o) => {
          const count = o.voter_user_ids.length;
          const isMine = poll.my_vote_option_id === o.id;
          const isWinner = isClosed && count > 0 && count === winnerCount;
          const ratio = count / maxVotes;
          return (
            <div
              key={o.id}
              className={[
                "relative overflow-hidden rounded-tile px-2.5 py-2 text-sm",
                isMine ? "ring-1 ring-tg-link/60" : "",
                isWinner
                  ? "bg-status-free/15"
                  : "bg-tg-bg/60",
              ].join(" ")}
            >
              <div
                className="absolute inset-y-0 left-0 bg-tg-link/15"
                style={{ width: `${ratio * 100}%` }}
              />
              <div className="relative flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium truncate">
                    {isWinner && (
                      <Icon
                        name="award"
                        size={12}
                        className="mr-1 inline-block align-[-2px]"
                      />
                    )}
                    {o.label ??
                      format(new Date(o.starts_at), "d MMM HH:mm", { locale: ru })}
                  </div>
                  {o.voter_user_ids.length > 0 && (
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {o.voter_user_ids.map((uid) => {
                        const u = usersById.get(uid);
                        return (
                          <span
                            key={uid}
                            title={u?.display_name ?? `#${uid}`}
                            className="w-4 h-4 rounded-full overflow-hidden inline-flex items-center justify-center text-white text-3xs"
                            style={{ background: u?.color_hex ?? "#888" }}
                          >
                            {u?.avatar_url ? (
                              <img
                                src={u.avatar_url}
                                alt=""
                                className="w-full h-full object-cover"
                              />
                            ) : (
                              (u?.display_name[0] ?? "?")
                            )}
                          </span>
                        );
                      })}
                    </div>
                  )}
                </div>
                <div className="font-mono text-xs tabular-nums text-tg-hint shrink-0">
                  {count}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {poll.my_vote_option_id == null && !isClosed && (
        <div className="mt-2 text-xs text-tg-hint">
          Голосуй прямо в Telegram-чате — результат подтянется сюда.
        </div>
      )}
      {poll.my_vote_option_id != null && (
        <div className="mt-2 text-xs text-tg-link">
          Твой голос учтён{usersById.get(meId) ? "" : ""}.
        </div>
      )}
    </motion.div>
  );
}

function pluralVotes(n: number): string {
  const m100 = n % 100;
  const m10 = n % 10;
  if (m100 >= 11 && m100 <= 14) return "голосов";
  if (m10 === 1) return "голос";
  if (m10 >= 2 && m10 <= 4) return "голоса";
  return "голосов";
}

function PollsSkeleton() {
  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="rounded-card bg-tg-secondary-bg/60 p-3 shadow-sm animate-pulse"
        >
          <div className="h-4 w-2/3 rounded-tile bg-tg-bg/60" />
          <div className="mt-2 h-3 w-1/3 rounded-tile bg-tg-bg/40" />
          <div className="mt-3 space-y-1.5">
            <div className="h-9 rounded-tile bg-tg-bg/40" />
            <div className="h-9 rounded-tile bg-tg-bg/40" />
            <div className="h-9 rounded-tile bg-tg-bg/30" />
          </div>
        </div>
      ))}
    </div>
  );
}
