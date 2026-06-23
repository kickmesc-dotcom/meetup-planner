/**
 * GHG8 P4.1.d–e: меню профиля. Заменяет вкладку «Топы» в нижнем меню:
 * топы теперь живут здесь (команда /top в чате — текстовое зеркало),
 * рядом — история лохов/чуханов и персональные настройки приветствия
 * (вернуть баннер, формат отображения званий).
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchUiPrefs,
  updateUiPrefs,
  type UiPrefs,
  type WelcomeFormat,
} from "@/api/availability";
import { fetchLoserHistory, fetchLoserStats } from "@/api/meetings";
import { fetchChukhanHistory } from "@/api/birthdays";
import { fetchChukhanLeaderboard } from "@/api/admin";
import type { User } from "@/types";
import { haptic } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import LeaderboardScreen from "../leaderboard/LeaderboardScreen";

interface Props {
  users: User[];
  me: User;
}

type Inner = "root" | "tops" | "history";

export default function ProfileScreen({ users, me }: Props) {
  const [inner, setInner] = useState<Inner>("root");

  if (inner === "tops") {
    return (
      <InnerScreen title="🏆 Топы" onBack={() => setInner("root")}>
        <LeaderboardScreen users={users} />
      </InnerScreen>
    );
  }
  if (inner === "history") {
    return (
      <InnerScreen title="📜 История" onBack={() => setInner("root")}>
        <HistorySection users={users} />
      </InnerScreen>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      {/* F1 (T1.5): крупная аватарка по центру → сводка → Топы → История. */}
      <ProfileHeader me={me} />

      <NavCard
        icon="🏆"
        title="Топы"
        subtitle="Чуханы и лохи за всё время (в чате — /top)"
        onClick={() => {
          haptic("selection");
          setInner("tops");
        }}
      />
      <NavCard
        icon="📜"
        title="История"
        subtitle="Кто когда был лохом дня и чуханом недели"
        onClick={() => {
          haptic("selection");
          setInner("history");
        }}
      />

      <GreetingSettings />
    </div>
  );
}

/**
 * F1 (T1.5): шапка профиля — крупная аватарка по центру, имя/@username, ниже
 * сводка «сколько раз был лохом / чуханом». Счётчики берём из тех же публичных
 * эндпоинтов, что и Топы (loser/stats + chukhan/leaderboard) — отдельного API
 * не заводим.
 */
function ProfileHeader({ me }: { me: User }) {
  const loserStats = useQuery({
    queryKey: ["loser", "stats"],
    queryFn: fetchLoserStats,
  });
  const chukhanLeaders = useQuery({
    queryKey: ["chukhan", "leaderboard"],
    queryFn: fetchChukhanLeaderboard,
  });

  const loserCount = loserStats.data?.counts?.[me.id] ?? 0;
  const chukhanCount =
    chukhanLeaders.data?.find((r) => r.user_id === me.id)?.count ?? 0;
  const loading = loserStats.isPending || chukhanLeaders.isPending;

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-4 flex flex-col items-center text-center">
      <div
        className="w-24 h-24 rounded-full overflow-hidden flex items-center justify-center text-white text-3xl font-semibold shrink-0"
        style={{ background: me.color_hex ?? "#888" }}
      >
        {me.avatar_url ? (
          <img src={me.avatar_url} alt="" className="w-full h-full object-cover" />
        ) : (
          me.display_name[0]
        )}
      </div>
      <div className="mt-3 text-lg font-semibold">{me.display_name}</div>
      {me.username && (
        <div className="text-xs text-tg-hint">@{me.username}</div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-2 w-full">
        <StatCell icon="🤡" label="Был лохом" value={loserCount} loading={loading} />
        <StatCell icon="💩" label="Был чуханом" value={chukhanCount} loading={loading} />
      </div>
    </section>
  );
}

function StatCell({
  icon,
  label,
  value,
  loading,
}: {
  icon: string;
  label: string;
  value: number;
  loading: boolean;
}) {
  return (
    <div className="rounded-lg bg-tg-bg/50 px-3 py-2 flex items-center gap-2">
      <span className="text-xl shrink-0">{icon}</span>
      <div className="min-w-0 text-left">
        <div className="text-lg font-semibold tabular-nums leading-tight">
          {loading ? "…" : value}
        </div>
        <div className="text-[11px] text-tg-hint truncate">{label}</div>
      </div>
    </div>
  );
}

/** P4.1.c/b: вернуть приветствие + единый формат отображения званий. */
function GreetingSettings() {
  const qc = useQueryClient();
  const prefs = useQuery({ queryKey: ["ui-prefs"], queryFn: fetchUiPrefs });

  const save = useMutation({
    mutationFn: updateUiPrefs,
    onSuccess: (out) => {
      haptic("success");
      qc.setQueryData<UiPrefs>(["ui-prefs"], out);
    },
    onError: () => haptic("error"),
  });

  const p = prefs.data;

  // GHG8 T1.3 (F2/F3): обе настройки ужаты в одну строку каждая (label слева,
  // контрол справа) — раньше блок занимал ~четверть экрана, а фича не настолько
  // важная (прод-фидбек 10.06 п.2/п.3).
  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3 divide-y divide-tg-bg/40">
      {!p ? (
        <ListSkeleton rows={2} />
      ) : (
        <>
          {/* F2: приветствие — описание-лейбл + тогл в одну строку. */}
          <div className="flex items-center justify-between gap-3 pb-2.5">
            <div className="min-w-0">
              <div className="text-sm text-tg-text">👋 Приветствие</div>
              <div className="text-[11px] text-tg-hint truncate">
                Баннер званий над календарём
              </div>
            </div>
            <Switch
              checked={!p.hide_greeting}
              onChange={(show) => save.mutate({ hide_greeting: !show })}
            />
          </div>
          {/* F3: формат участника — лейбл + компактный сегмент-контрол в строку. */}
          <div className="flex items-center justify-between gap-3 pt-2.5">
            <div className="text-sm text-tg-text shrink-0">Формат</div>
            <div className="flex rounded-lg bg-tg-bg/60 p-0.5 text-xs shrink-0">
              {(
                [
                  ["avatar", "Аватар"],
                  ["name", "Имя"],
                  ["both", "Оба"],
                ] as [WelcomeFormat, string][]
              ).map(([fmt, label]) => (
                <button
                  key={fmt}
                  type="button"
                  aria-label={
                    fmt === "avatar"
                      ? "Аватарка"
                      : fmt === "name"
                        ? "Имя"
                        : "Имя + аватарка"
                  }
                  onClick={() => {
                    if (p.welcome_format === fmt) return;
                    haptic("selection");
                    save.mutate({ welcome_format: fmt });
                  }}
                  className={[
                    "min-h-8 px-2.5 rounded-md transition-colors",
                    p.welcome_format === fmt
                      ? "bg-tg-button text-tg-button-text font-medium"
                      : "text-tg-hint",
                  ].join(" ")}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

/** P4.1.e: история лохов дня + чуханов недели (публичные эндпоинты).
 *  F1 (T1.5): в строке теперь и причина (у лоха уже была, у чухана — после T1.2). */
function HistorySection({ users }: { users: User[] }) {
  const losers = useQuery({
    queryKey: ["loser", "history"],
    queryFn: () => fetchLoserHistory(20),
  });
  const chukhans = useQuery({
    queryKey: ["chukhan", "history-public"],
    queryFn: () => fetchChukhanHistory(20),
  });
  const byId = Object.fromEntries(users.map((u) => [u.id, u] as const));

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold">💩 Чуханы недели</div>
        <div className="text-xs text-tg-hint mb-2">Последние 20 недель</div>
        {chukhans.isPending ? (
          <ListSkeleton rows={4} />
        ) : !chukhans.data?.length ? (
          <div className="text-xs text-tg-hint py-2">Чуханов ещё не было.</div>
        ) : (
          <div className="divide-y divide-tg-bg/40">
            {chukhans.data.map((r) => (
              <Row
                key={r.week_start}
                date={r.week_start}
                user={byId[r.user_id]}
                fallback={`id=${r.user_id}`}
                reason={r.reason_text}
              />
            ))}
          </div>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold">👑 Лохи дня</div>
        <div className="text-xs text-tg-hint mb-2">Последние 20 роллов</div>
        {losers.isPending ? (
          <ListSkeleton rows={4} />
        ) : !losers.data?.length ? (
          <div className="text-xs text-tg-hint py-2">Никто ещё не попадался.</div>
        ) : (
          <div className="divide-y divide-tg-bg/40">
            {losers.data.map((r) => (
              <Row
                key={r.id}
                date={r.rolled_at}
                user={byId[r.loser_user_id]}
                fallback={`id=${r.loser_user_id}`}
                reason={r.reason_text}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Row({
  date,
  user,
  fallback,
  reason,
}: {
  date: string;
  user: User | undefined;
  fallback: string;
  reason: string | null;
}) {
  const d = new Date(date);
  const dateStr = isNaN(d.getTime())
    ? date
    : d.toLocaleDateString("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        year: "2-digit",
      });
  return (
    <div className="flex items-start gap-2 py-1.5">
      <div
        className="w-6 h-6 rounded-full overflow-hidden inline-flex items-center justify-center text-white text-[10px] shrink-0"
        style={{ background: user?.color_hex ?? "#888" }}
      >
        {user?.avatar_url ? (
          <img src={user.avatar_url} alt="" className="w-full h-full object-cover" />
        ) : (
          (user?.display_name[0] ?? "?")
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm truncate">{user?.display_name ?? fallback}</div>
        {reason && (
          <div className="text-[11px] text-tg-hint italic line-clamp-2">«{reason}»</div>
        )}
      </div>
      <span className="text-xs text-tg-hint tabular-nums shrink-0">{dateStr}</span>
    </div>
  );
}

function NavCard({
  icon,
  title,
  subtitle,
  onClick,
}: {
  icon: string;
  title: string;
  subtitle: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left rounded-xl bg-tg-secondary-bg/60 p-3 flex items-center gap-3 active:scale-[0.98] transition-transform"
    >
      <div className="w-10 h-10 rounded-lg bg-tg-bg/60 flex items-center justify-center text-2xl shrink-0">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-tg-text">{title}</div>
        <div className="text-[11px] text-tg-hint truncate">{subtitle}</div>
      </div>
      <div className="text-tg-hint text-base">›</div>
    </button>
  );
}

function InnerScreen({
  title,
  onBack,
  children,
}: {
  title: string;
  onBack: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-tg-secondary-bg">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onBack();
          }}
          className="min-h-9 min-w-9 rounded-md bg-tg-secondary-bg/60 px-2 text-sm text-tg-link active:scale-95 transition-transform"
          aria-label="Назад"
        >
          ←
        </button>
        <div className="text-sm font-semibold truncate">{title}</div>
      </div>
      {children}
    </div>
  );
}

function Switch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => {
        haptic("selection");
        onChange(!checked);
      }}
      className={[
        "shrink-0 inline-flex h-6 w-11 items-center rounded-full transition-colors",
        checked ? "bg-tg-button" : "bg-tg-hint/30",
      ].join(" ")}
      role="switch"
      aria-checked={checked}
    >
      <span
        className={[
          "inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-5" : "translate-x-0.5",
        ].join(" ")}
      />
    </button>
  );
}
