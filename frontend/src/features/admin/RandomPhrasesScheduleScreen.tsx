import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchRPSchedule,
  fetchRandomPhrases,
  updateRPSchedule,
  updateRandomPhrases,
  type RPScheduleMode,
} from "@/api/admin";
import { haptic } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

const MODE_LABELS: Record<RPScheduleMode, string> = {
  daily_n: "N раз в сутки",
  weekly_n: "N раз в неделю",
  fixed_times: "Фикс. времена",
  random_interval: "Random интервал",
};

export default function RandomPhrasesScheduleScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const schedule = useQuery({ queryKey: ["admin", "rp-schedule"], queryFn: fetchRPSchedule });
  const enable = useQuery({ queryKey: ["admin", "phrases"], queryFn: fetchRandomPhrases });

  const setSchedule = useMutation({
    mutationFn: updateRPSchedule,
    onSuccess: () => {
      haptic("light");
      qc.invalidateQueries({ queryKey: ["admin", "rp-schedule"] });
      qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
    },
    onError: () => haptic("error"),
  });
  const setEnabled = useMutation({
    mutationFn: updateRandomPhrases,
    onSuccess: () => {
      haptic("light");
      qc.invalidateQueries({ queryKey: ["admin", "phrases"] });
    },
    onError: () => haptic("error"),
  });

  return (
    <SubScreen
      title="💬 Автопост рандомных фраз"
      subtitle="Когда бот публикует Шизо-цитату"
      onBack={onBack}
    >
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        {enable.isPending || !enable.data ? (
          <ListSkeleton rows={1} />
        ) : (
          <label
            className={`flex items-center justify-between gap-2 rounded-lg px-2 py-2.5 transition-colors ${
              enable.data.enabled ? "bg-status-free/10" : "bg-tg-bg/40"
            }`}
          >
            <span className="text-sm font-medium text-tg-text">
              {enable.data.enabled ? "🔔 Авто-постинг включён" : "🔕 Авто-постинг выключен"}
            </span>
            <input
              type="checkbox"
              disabled={setEnabled.isPending}
              checked={enable.data.enabled}
              onChange={(e) =>
                setEnabled.mutate({ enabled: e.target.checked, count: enable.data!.count })
              }
              className="h-6 w-6 accent-status-free disabled:opacity-50"
            />
          </label>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">📅 Режим расписания</div>
        <div className="text-xs text-tg-hint mb-2">
          Когда срабатывает job автопостинга. Сохранение пересоберёт APScheduler.
        </div>
        {schedule.isPending || !schedule.data ? (
          <ListSkeleton rows={3} />
        ) : (
          <ScheduleEditor
            initialMode={schedule.data.mode}
            initialParam={schedule.data.param}
            isPending={setSchedule.isPending}
            onSave={(mode, param) => setSchedule.mutate({ mode, param })}
          />
        )}
        {setSchedule.isError && (
          <div className="mt-2 rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {String((setSchedule.error as Error)?.message ?? setSchedule.error)}
          </div>
        )}
      </section>
    </SubScreen>
  );
}

function ScheduleEditor({
  initialMode,
  initialParam,
  isPending,
  onSave,
}: {
  initialMode: RPScheduleMode;
  initialParam: Record<string, unknown>;
  isPending: boolean;
  onSave: (mode: RPScheduleMode, param: Record<string, unknown>) => void;
}) {
  const [mode, setMode] = useState<RPScheduleMode>(initialMode);
  const [dailyN, setDailyN] = useState(String((initialParam.n as number | undefined) ?? 1));
  const [weeklyN, setWeeklyN] = useState(String((initialParam.n as number | undefined) ?? 2));
  const [times, setTimes] = useState<string[]>(
    Array.isArray(initialParam.times) ? (initialParam.times as string[]) : ["19:37"],
  );
  const [minInterval, setMinInterval] = useState(
    String((initialParam.min_minutes as number | undefined) ?? 120),
  );
  const [draftTime, setDraftTime] = useState("");

  useEffect(() => {
    setMode(initialMode);
    setDailyN(String((initialParam.n as number | undefined) ?? 1));
    setWeeklyN(String((initialParam.n as number | undefined) ?? 2));
    setTimes(Array.isArray(initialParam.times) ? (initialParam.times as string[]) : ["19:37"]);
    setMinInterval(String((initialParam.min_minutes as number | undefined) ?? 120));
  }, [initialMode, initialParam]);

  const buildParam = (): Record<string, unknown> => {
    if (mode === "daily_n") return { n: clamp(parseInt(dailyN, 10) || 1, 1, 24) };
    if (mode === "weekly_n") return { n: clamp(parseInt(weeklyN, 10) || 2, 1, 7) };
    if (mode === "fixed_times") return { times: times.filter(isValidHHMM) };
    return { min_minutes: clamp(parseInt(minInterval, 10) || 120, 15, 1440) };
  };

  const addTime = () => {
    if (!isValidHHMM(draftTime)) {
      haptic("warning");
      return;
    }
    if (times.includes(draftTime)) {
      haptic("warning");
      return;
    }
    setTimes([...times, draftTime].sort());
    setDraftTime("");
    haptic("selection");
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-1.5">
        {(Object.keys(MODE_LABELS) as RPScheduleMode[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => {
              haptic("selection");
              setMode(m);
            }}
            className={[
              "min-h-11 rounded-lg px-2 py-2 text-xs font-medium transition-colors",
              mode === m
                ? "bg-tg-link/20 text-tg-link border border-tg-link/40"
                : "bg-tg-bg/50 text-tg-text border border-transparent",
            ].join(" ")}
          >
            {MODE_LABELS[m]}
          </button>
        ))}
      </div>

      {mode === "daily_n" && (
        <div className="flex items-center gap-2 rounded-lg bg-tg-bg/40 px-2 py-2">
          <span className="text-sm text-tg-text">N в сутки:</span>
          <input
            type="text"
            inputMode="numeric"
            value={dailyN}
            onChange={(e) => setDailyN(e.target.value.replace(/[^0-9]/g, ""))}
            className="w-16 rounded-md bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text text-center tabular-nums outline-none border border-transparent focus:border-tg-link"
          />
          <span className="text-xs text-tg-hint">1..24</span>
        </div>
      )}

      {mode === "weekly_n" && (
        <div className="flex items-center gap-2 rounded-lg bg-tg-bg/40 px-2 py-2">
          <span className="text-sm text-tg-text">N в неделю:</span>
          <input
            type="text"
            inputMode="numeric"
            value={weeklyN}
            onChange={(e) => setWeeklyN(e.target.value.replace(/[^0-9]/g, ""))}
            className="w-16 rounded-md bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text text-center tabular-nums outline-none border border-transparent focus:border-tg-link"
          />
          <span className="text-xs text-tg-hint">1..7 (в 19:37 в N дней)</span>
        </div>
      )}

      {mode === "fixed_times" && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="HH:MM"
              value={draftTime}
              onChange={(e) => setDraftTime(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addTime();
                }
              }}
              className="flex-1 rounded-md bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text placeholder:text-tg-hint outline-none border border-transparent focus:border-tg-link"
            />
            <button
              type="button"
              onClick={addTime}
              disabled={!isValidHHMM(draftTime)}
              className="min-h-11 rounded-md bg-tg-link/15 px-3 text-xs text-tg-link disabled:opacity-40"
            >
              + добавить
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {times.length === 0 && (
              <div className="text-xs text-tg-hint">Добавь хотя бы одно время.</div>
            )}
            {times.map((t) => (
              <div
                key={t}
                className="flex items-center gap-1 rounded-full bg-tg-link/15 pl-2 pr-1 py-1 text-xs text-tg-link"
              >
                <span>{t}</span>
                <button
                  type="button"
                  onClick={() => {
                    haptic("warning");
                    setTimes(times.filter((x) => x !== t));
                  }}
                  className="w-5 h-5 rounded-full bg-tg-link/30 text-[10px]"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {mode === "random_interval" && (
        <div className="flex items-center gap-2 rounded-lg bg-tg-bg/40 px-2 py-2">
          <span className="text-sm text-tg-text">Базовый интервал:</span>
          <input
            type="text"
            inputMode="numeric"
            value={minInterval}
            onChange={(e) => setMinInterval(e.target.value.replace(/[^0-9]/g, ""))}
            className="w-20 rounded-md bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text text-center tabular-nums outline-none border border-transparent focus:border-tg-link"
          />
          <span className="text-xs text-tg-hint">мин (15..1440, jitter ±50%)</span>
        </div>
      )}

      <button
        type="button"
        disabled={isPending || (mode === "fixed_times" && times.filter(isValidHHMM).length === 0)}
        onClick={() => onSave(mode, buildParam())}
        className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform"
      >
        {isPending ? "Сохраняем…" : "💾 Сохранить расписание"}
      </button>
    </div>
  );
}

function isValidHHMM(s: string): boolean {
  return /^([01]?\d|2[0-3]):[0-5]\d$/.test(s.trim());
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}
