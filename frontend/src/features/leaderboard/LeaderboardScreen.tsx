import { useQuery } from "@tanstack/react-query";
import { fetchLoserStats } from "@/api/meetings";
import { fetchChukhanLeaderboard, type ChukhanLeaderRow } from "@/api/admin";
import { fetchRanksChart } from "@/api/game";
import type { User } from "@/types";
import { ListSkeleton } from "@/components/Skeleton";
import RankPlaque from "@/components/RankPlaque";

interface Props {
  users: User[];
}

/**
 * Топы — «реестр званий». Identity: цифры ведём моношрифтом с tabular-nums
 * (это счётчик, а не текст), мерная линейка квадратная (скругления — язык
 * карточек, а не реестра), а лидер строки получает единственную печать
 * приложения — штамп `ink-stamp`. Всё остальное намеренно тихое.
 */
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
      {/* GHG11(13): САМЫЙ верх — топ по рейтингу: уровень, опыт и процент
          собранных ачивок. Чуханы и лохи — ниже, как привычный реестр званий. */}
      <RatingTop users={users} />
      <Section
        icon="💩"
        title="Топ чуханов"
        subtitle="Сколько недель каждый носил звание"
        rows={(chukhans.data ?? []).map((r) => ({ user_id: r.user_id, count: r.count }))}
        users={users}
        empty="Чуханов ещё не было."
        loading={chukhans.isPending}
      />
      <Section
        icon="🎲"
        title="Топ лохов дня"
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

/**
 * GHG11(13): верхний топ по рейтингу — «кто выше по уровню и опыту».
 *
 * Строка отвечает на три вопроса сразу: место, сколько опыта и насколько
 * собрана коллекция ачивок. Значения — моношрифтом с tabular-nums (это цифры,
 * а не текст), ранг показываем плашкой, как в профиле.
 */
function RatingTop({ users }: { users: User[] }) {
  const ranks = useQuery({ queryKey: ["game", "ranks"], queryFn: fetchRanksChart });
  const userById = Object.fromEntries(users.map((u) => [u.id, u] as const));
  return (
    <section
      data-testid="rating-top"
      className="rounded-xl bg-tg-secondary-bg border border-tg-hint/10 p-3"
    >
      <header className="flex items-center gap-2">
        <span
          aria-hidden
          className="grid h-8 w-8 shrink-0 place-items-center bg-ink-stamp text-[17px] leading-none text-white"
        >
          🏆
        </span>
        <div className="min-w-0">
          <h2 className="text-sm font-bold uppercase leading-tight tracking-[0.08em]">
            Топ по рейтингу
          </h2>
          <p className="truncate text-2xs text-muted">
            Опыт, уровень и собранные ачивки
          </p>
        </div>
      </header>

      {ranks.isPending ? (
        <div className="mt-3">
          <ListSkeleton rows={4} />
        </div>
      ) : !ranks.data?.length ? (
        <p className="mt-3 text-xs text-muted">Ещё никто не прокачался.</p>
      ) : (
        <ol className="mt-3 space-y-1.5">
          {ranks.data.map((r, i) => {
            const u = userById[r.user_id];
            return (
              <li key={r.user_id} className="flex items-center gap-2 px-1.5 py-1">
                <span className="w-4 shrink-0 text-right font-mono text-2xs tabular-nums text-muted">
                  {i + 1}
                </span>
                <div
                  className="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-full text-2xs font-medium text-white"
                  style={{ background: u?.color_hex ?? "#888" }}
                >
                  {u?.avatar_url ? (
                    <img src={u.avatar_url} alt="" className="h-full w-full object-cover" />
                  ) : (
                    (u?.display_name[0] ?? "?")
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {u?.display_name ?? `id=${r.user_id}`}
                  </div>
                  <div className="flex items-center gap-1.5 text-2xs tabular-nums text-muted">
                    <span>Ур. {r.level}</span>
                    <span className="text-tg-text">{r.xp} XP</span>
                  </div>
                </div>
                {r.rank_name && (
                  <span className="hidden shrink-0 sm:block">
                    <RankPlaque hex={r.hex} bold={r.bold || r.supreme}>
                      {r.rank_name}
                    </RankPlaque>
                  </span>
                )}
                <span
                  title={`Собрано ачивок: ${r.achievements_collected ?? 0} из ${
                    r.achievements_total ?? 0
                  }`}
                  className="shrink-0 rounded-md bg-tg-bg/60 px-1.5 py-0.5 text-2xs tabular-nums text-tg-text"
                >
                  🏅 {r.achievements_percent ?? 0}%
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function Section({
  icon,
  title,
  subtitle,
  rows,
  users,
  empty,
  loading,
}: {
  icon: string;
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
    <section className="rounded-xl bg-tg-secondary-bg border border-tg-hint/10 p-3">
      <header className="flex items-center gap-2">
        <span
          aria-hidden
          className="grid h-8 w-8 shrink-0 place-items-center bg-ink-stamp text-[17px] leading-none text-white"
        >
          {icon}
        </span>
        <div className="min-w-0">
          <h2 className="text-sm font-bold uppercase leading-tight tracking-[0.08em]">
            {title}
          </h2>
          <p className="truncate text-2xs text-muted">{subtitle}</p>
        </div>
      </header>

      {loading ? (
        <div className="mt-3">
          <ListSkeleton rows={4} />
        </div>
      ) : sorted.length === 0 ? (
        <p className="mt-3 text-xs text-muted">{empty}</p>
      ) : (
        <ol className="mt-3 space-y-2">
          {sorted.map((r, i) => {
            const u = userById[r.user_id];
            const ratio = (r.count / max) * 100;
            const leader = i === 0;
            return (
              <li
                key={r.user_id}
                className="relative flex items-center gap-2 overflow-hidden px-1.5 py-1"
              >
                {/* Мера — заливка строки (как на табло), а не линейка под именем:
                    подчёркивание читалось как типографика, а не как величина. */}
                <span
                  aria-hidden
                  className={[
                    "absolute inset-y-0 left-0",
                    leader ? "bg-ink-stamp/10" : "bg-tg-hint/10",
                  ].join(" ")}
                  style={{ width: `${ratio}%` }}
                />
                <span className="relative w-4 shrink-0 text-right font-mono text-2xs tabular-nums text-muted">
                  {i + 1}
                </span>
                <div
                  className="relative flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-full text-2xs font-medium text-white"
                  style={{ background: u?.color_hex ?? "#888" }}
                >
                  {u?.avatar_url ? (
                    <img src={u.avatar_url} alt="" className="h-full w-full object-cover" />
                  ) : (
                    (u?.display_name[0] ?? "?")
                  )}
                </div>
                <span className="relative min-w-0 flex-1 truncate text-sm font-medium">
                  {u?.display_name ?? `id=${r.user_id}`}
                </span>
                {/* Лидера выделяем ВЕСОМ, а не цветом: `ink-stamp` как текст не
                    проходит контраст на тёмной теме (он задуман как фон печати). */}
                <span
                  className={[
                    "relative shrink-0 font-mono text-sm tabular-nums text-tg-text",
                    leader ? "font-bold" : "font-semibold",
                  ].join(" ")}
                >
                  {r.count}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
