import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { fetchRandomPhrasesPool, triggerRandomPhrases } from "@/api/admin";
import type { User } from "@/types";
import { haptic } from "@/tg/webapp";
import ChukhanLoserScreen from "./ChukhanLoserScreen";
import ScheduledPublicationsScreen from "./ScheduledPublicationsScreen";
import RandomPhrasesScheduleScreen from "./RandomPhrasesScheduleScreen";
import RandomPhrasesGeneratorScreen from "./RandomPhrasesGeneratorScreen";
import AutoLoserScreen from "./AutoLoserScreen";
import HistoryScreen from "./HistoryScreen";
import BirthdaysScreen from "./BirthdaysScreen";

type Section =
  | "root"
  | "chukhan-loser"
  | "scheduled-pubs"
  | "rp-schedule"
  | "rp-generator"
  | "autoloser"
  | "history"
  | "birthdays";

interface Props {
  users: User[];
}

export default function AdminScreen({ users }: Props) {
  const [section, setSection] = useState<Section>("root");
  const [poolOpen, setPoolOpen] = useState(false);

  const runPhrases = useMutation({
    mutationFn: triggerRandomPhrases,
    onSuccess: () => haptic("success"),
    onError: () => haptic("error"),
  });

  const pool = useQuery({
    queryKey: ["admin", "rp-pool"],
    queryFn: fetchRandomPhrasesPool,
    enabled: poolOpen,
    staleTime: 30_000,
  });

  const back = () => setSection("root");

  if (section === "chukhan-loser") return <ChukhanLoserScreen users={users} onBack={back} />;
  if (section === "scheduled-pubs") return <ScheduledPublicationsScreen onBack={back} />;
  if (section === "rp-schedule") return <RandomPhrasesScheduleScreen onBack={back} />;
  if (section === "rp-generator") return <RandomPhrasesGeneratorScreen onBack={back} />;
  if (section === "autoloser") return <AutoLoserScreen onBack={back} />;
  if (section === "history") return <HistoryScreen users={users} onBack={back} />;
  if (section === "birthdays") return <BirthdaysScreen onBack={back} />;

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-3">
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-2">⚡ Быстрые действия</div>
        <button
          type="button"
          disabled={runPhrases.isPending}
          onClick={() => {
            haptic("medium");
            runPhrases.mutate();
          }}
          className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-50 active:scale-[0.98] transition-transform"
        >
          {runPhrases.isPending ? "⏳ Постим…" : "🚀 Прогнать рандомную фразу сейчас"}
        </button>
        {runPhrases.isError && (
          <div className="mt-2 rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {String((runPhrases.error as Error)?.message ?? runPhrases.error)}
          </div>
        )}
        {runPhrases.isSuccess && !runPhrases.isPending && (
          <div className="mt-2 rounded-md bg-status-free/10 p-2 text-xs text-status-free">
            ✓ Запустили — проверь чат.
          </div>
        )}

        <button
          type="button"
          onClick={() => {
            haptic("selection");
            setPoolOpen((v) => !v);
          }}
          className="mt-2 w-full min-h-9 rounded-lg bg-tg-bg/60 px-2 py-1.5 text-xs text-tg-text flex items-center justify-between active:scale-[0.99] transition-transform"
        >
          <span>📊 Пул фраз сейчас{pool.data ? ` (${pool.data.total_chunks})` : ""}</span>
          <span className="text-tg-hint">{poolOpen ? "▾" : "▸"}</span>
        </button>
        {poolOpen && (
          <div className="mt-2 rounded-md bg-tg-bg/40 p-2 text-xs">
            {pool.isPending ? (
              <div className="text-tg-hint">Считаем…</div>
            ) : pool.isError ? (
              <div className="text-status-busy">⚠ {String((pool.error as Error)?.message ?? pool.error)}</div>
            ) : pool.data ? (
              <>
                <div className="text-tg-hint mb-1">
                  За {pool.data.lookback_days} дн · всего {pool.data.total_chunks} кусков
                </div>
                <ul className="space-y-0.5">
                  {pool.data.rows.map((r) => (
                    <li
                      key={r.user_id}
                      className="flex items-center justify-between gap-2"
                    >
                      <span className="truncate text-tg-text">{r.display_name}</span>
                      <span
                        className={`tabular-nums ${
                          r.chunks_count === 0 ? "text-status-busy" : "text-tg-text"
                        }`}
                      >
                        {r.chunks_count}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        )}
      </section>

      <Card
        icon="💩"
        title="Чухан / Лох"
        subtitle="Веса, ре-ролл, кастомные фразы"
        onClick={() => {
          haptic("selection");
          setSection("chukhan-loser");
        }}
      />
      <Card
        icon="⏱️"
        title="Запланированные публикации"
        subtitle="Тик напоминаний, очередь job'ов, опросы"
        onClick={() => {
          haptic("selection");
          setSection("scheduled-pubs");
        }}
      />
      <Card
        icon="💬"
        title="Автопост рандомных фраз"
        subtitle="Расписание (N раз/день, фикс-времена, рандом-интервал)"
        onClick={() => {
          haptic("selection");
          setSection("rp-schedule");
        }}
      />
      <Card
        icon="🧪"
        title="Генератор рандомных фраз"
        subtitle="Длина цитаты, глубина истории, шансы"
        onClick={() => {
          haptic("selection");
          setSection("rp-generator");
        }}
      />
      <Card
        icon="🤡"
        title="Автолох"
        subtitle="Бот сам выбирает лоха в окне дня"
        onClick={() => {
          haptic("selection");
          setSection("autoloser");
        }}
      />
      <Card
        icon="🎂"
        title="Дни рождения"
        subtitle="Дата + что напоминать по каждому"
        onClick={() => {
          haptic("selection");
          setSection("birthdays");
        }}
      />
      <Card
        icon="📜"
        title="История"
        subtitle="Чуханы недели + лохи дня"
        onClick={() => {
          haptic("selection");
          setSection("history");
        }}
      />
    </div>
  );
}

function Card({
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
