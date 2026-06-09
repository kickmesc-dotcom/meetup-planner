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
import { fetchLoserHistory } from "@/api/meetings";
import { fetchChukhanHistory } from "@/api/birthdays";
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
      {/* Шапка профиля */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 flex items-center gap-3">
        <div
          className="w-12 h-12 rounded-full overflow-hidden flex items-center justify-center text-white text-lg font-medium shrink-0"
          style={{ background: me.color_hex ?? "#888" }}
        >
          {me.avatar_url ? (
            <img src={me.avatar_url} alt="" className="w-full h-full object-cover" />
          ) : (
            me.display_name[0]
          )}
        </div>
        <div className="min-w-0">
          <div className="text-base font-semibold truncate">{me.display_name}</div>
          {me.username && (
            <div className="text-xs text-tg-hint truncate">@{me.username}</div>
          )}
        </div>
      </section>

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

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
      <div>
        <div className="text-sm font-semibold text-tg-text">👋 Приветствие</div>
        <div className="text-[11px] text-tg-hint">
          Баннер с быстрой инфой (чухан, лохи, червь) над календарём.
        </div>
      </div>
      {!p ? (
        <ListSkeleton rows={2} />
      ) : (
        <>
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm text-tg-text">Показывать баннер</div>
            <Switch
              checked={!p.hide_greeting}
              onChange={(show) => save.mutate({ hide_greeting: !show })}
            />
          </div>
          <div>
            <div className="text-[11px] text-tg-hint mb-1">
              Формат участника в блоках званий (один на все блоки)
            </div>
            <div className="flex rounded-lg bg-tg-bg/60 p-0.5 text-xs">
              {(
                [
                  ["avatar", "Аватарка"],
                  ["name", "Имя"],
                  ["both", "Имя + аватарка"],
                ] as [WelcomeFormat, string][]
              ).map(([fmt, label]) => (
                <button
                  key={fmt}
                  type="button"
                  onClick={() => {
                    if (p.welcome_format === fmt) return;
                    haptic("selection");
                    save.mutate({ welcome_format: fmt });
                  }}
                  className={[
                    "flex-1 min-h-9 rounded-md transition-colors",
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

/** P4.1.e: история лохов дня + чуханов недели (публичные эндпоинты). */
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
  const name = (uid: number) => byId[uid]?.display_name ?? `id=${uid}`;

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
          <div className="space-y-1">
            {chukhans.data.map((r) => (
              <Row
                key={r.week_start}
                date={r.week_start}
                label={name(r.user_id)}
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
          <div className="space-y-1">
            {losers.data.map((r) => (
              <Row key={r.id} date={r.rolled_at} label={name(r.loser_user_id)} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Row({ date, label }: { date: string; label: string }) {
  const d = new Date(date);
  const dateStr = isNaN(d.getTime())
    ? date
    : d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit" });
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span className="truncate">{label}</span>
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
