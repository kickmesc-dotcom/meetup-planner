import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  cancelScheduledJob,
  closeAdminPoll,
  deleteAdminPoll,
  fetchAdminPolls,
  fetchRemindersSettings,
  fetchScheduledJobs,
  updateRemindersSettings,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";

const errAlert = (e: unknown) => {
  haptic("error");
  void showAlert(humanizeApiError(e));
};

const JOBS_IDLE_INTERVAL_MS = 10 * 60 * 1000;
const JOBS_HOT_INTERVAL_MS = 5_000;
const JOBS_HOT_DURATION_MS = 3 * 60 * 1000;

interface Props {
  onBack: () => void;
}

export default function ScheduledPublicationsScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const [jobsHotUntil, setJobsHotUntil] = useState(0);
  const [, forceTick] = useState(0);
  const hotTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const enterHotMode = useCallback(() => {
    const until = Date.now() + JOBS_HOT_DURATION_MS;
    setJobsHotUntil(until);
    if (hotTimerRef.current) clearTimeout(hotTimerRef.current);
    hotTimerRef.current = setTimeout(() => {
      forceTick((n) => n + 1);
      hotTimerRef.current = null;
    }, JOBS_HOT_DURATION_MS + 100);
    qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
  }, [qc]);

  useEffect(() => {
    return () => {
      if (hotTimerRef.current) clearTimeout(hotTimerRef.current);
    };
  }, []);

  const isHot = Date.now() < jobsHotUntil;
  const jobsInterval = isHot ? JOBS_HOT_INTERVAL_MS : JOBS_IDLE_INTERVAL_MS;

  const jobs = useQuery({
    queryKey: ["admin", "jobs"],
    queryFn: fetchScheduledJobs,
    refetchInterval: jobsInterval,
  });
  const tick = useQuery({
    queryKey: ["admin", "reminders"],
    queryFn: fetchRemindersSettings,
  });
  const setTick = useMutation({
    mutationFn: updateRemindersSettings,
    onSuccess: () => {
      haptic("light");
      qc.invalidateQueries({ queryKey: ["admin", "reminders"] });
      qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
    },
    onError: errAlert,
  });
  const cancelJob = useMutation({
    mutationFn: (id: string) => cancelScheduledJob(id),
    onSuccess: () => {
      haptic("light");
      enterHotMode();
    },
    onError: errAlert,
  });

  const polls = useQuery({ queryKey: ["admin", "polls"], queryFn: fetchAdminPolls });
  const closePoll = useMutation({
    mutationFn: (id: number) => closeAdminPoll(id),
    onSuccess: () => {
      haptic("medium");
      qc.invalidateQueries({ queryKey: ["admin", "polls"] });
      qc.invalidateQueries({ queryKey: ["polls"] });
    },
    onError: errAlert,
  });
  const removePoll = useMutation({
    mutationFn: (id: number) => deleteAdminPoll(id),
    onSuccess: () => {
      haptic("heavy");
      qc.invalidateQueries({ queryKey: ["admin", "polls"] });
      qc.invalidateQueries({ queryKey: ["polls"] });
    },
    onError: errAlert,
  });

  return (
    <SubScreen
      title="⏱️ Запланированные публикации"
      subtitle="Тик напоминаний, очередь job'ов, опросы"
      onBack={onBack}
    >
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">⏰ Тик напоминаний</div>
        <div className="text-xs text-tg-hint mb-2">
          Раз в N минут бот проверяет очередь напоминаний к встречам. Дефолт — 10 минут.
        </div>
        {tick.isPending || !tick.data ? (
          <ListSkeleton rows={1} />
        ) : (
          <TickEditor
            initial={tick.data.tick_minutes}
            isPending={setTick.isPending}
            onSave={(v) => setTick.mutate(v)}
          />
        )}
        {setTick.isError && (
          <div className="mt-2 rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {String((setTick.error as Error)?.message ?? setTick.error)}
          </div>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="flex items-start justify-between gap-2 mb-1">
          <div className="text-base font-semibold">📋 Очередь задач</div>
          <button
            type="button"
            onClick={() => {
              haptic("light");
              enterHotMode();
              jobs.refetch();
            }}
            className="shrink-0 rounded-md bg-tg-bg/70 px-2 py-1 text-[10px] text-tg-hint active:scale-95 transition-transform"
            title="Обновить очередь и опрашивать чаще 3 минуты"
          >
            ↻ {isHot ? "тик 5с" : "тик 10м"}
          </button>
        </div>
        <div className="text-xs text-tg-hint mb-2">
          APScheduler-задачи + ближайшие напоминания.
        </div>
        {jobs.isPending ? (
          <ListSkeleton rows={3} />
        ) : (jobs.data ?? []).length === 0 ? (
          <div className="text-xs text-tg-hint">Очередь пуста.</div>
        ) : (
          <div className="space-y-1.5">
            {(jobs.data ?? []).map((j) => (
              <div
                key={j.id}
                className="flex items-center gap-2 rounded-lg bg-tg-bg/50 px-2 py-1.5"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate text-tg-text">{j.label}</div>
                  <div className="text-[10px] text-tg-hint truncate">
                    {j.next_run_at
                      ? format(new Date(j.next_run_at), "dd.MM HH:mm")
                      : "—"}
                  </div>
                </div>
                <div
                  className={[
                    "text-[10px] rounded-full px-1.5 py-0.5 shrink-0",
                    j.kind === "reminder"
                      ? "bg-status-maybe/15 text-status-maybe"
                      : "bg-tg-link/15 text-tg-link",
                  ].join(" ")}
                >
                  {j.kind}
                </div>
                {j.kind === "reminder" && (
                  <button
                    type="button"
                    onClick={() => {
                      if (confirm(`Отменить «${j.label}»?`)) cancelJob.mutate(j.id);
                    }}
                    disabled={cancelJob.isPending}
                    className="min-h-11 min-w-11 rounded-md bg-status-busy/15 px-2 text-xs text-status-busy disabled:opacity-40"
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">📊 Опросы в чате</div>
        <div className="text-xs text-tg-hint mb-2">
          Закрыть зависший опрос или удалить совсем — голоса каскадом. TG-сообщение
          удалится только если ему меньше 48 часов.
        </div>
        {polls.isPending ? (
          <ListSkeleton rows={3} />
        ) : (polls.data ?? []).length === 0 ? (
          <div className="text-xs text-tg-hint">Опросов нет.</div>
        ) : (
          <div className="space-y-1.5">
            {(polls.data ?? []).map((p) => (
              <div
                key={p.id}
                className="flex items-center gap-2 rounded-lg bg-tg-bg/50 px-2 py-1.5"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate text-tg-text">{p.question}</div>
                  <div className="text-[10px] text-tg-hint truncate">
                    #{p.id} · {format(new Date(p.created_at), "dd.MM HH:mm")}
                    {p.closes_at &&
                      ` · до ${format(new Date(p.closes_at), "dd.MM HH:mm")}`}
                  </div>
                </div>
                <div
                  className={[
                    "text-[10px] rounded-full px-1.5 py-0.5 shrink-0",
                    p.is_open
                      ? "bg-status-free/15 text-status-free"
                      : "bg-tg-hint/15 text-tg-hint",
                  ].join(" ")}
                >
                  {p.is_open ? "открыт" : "закрыт"}
                </div>
                {p.is_open && (
                  <button
                    type="button"
                    onClick={() => {
                      haptic("warning");
                      if (confirm(`Закрыть опрос «${p.question}»?`)) {
                        closePoll.mutate(p.id);
                      }
                    }}
                    disabled={closePoll.isPending}
                    className="min-h-11 min-w-11 rounded-md bg-status-maybe/15 px-2 text-xs text-status-maybe disabled:opacity-40"
                  >
                    🔒
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    haptic("warning");
                    if (
                      confirm(
                        `Удалить опрос «${p.question}» полностью? Голоса пропадут.`,
                      )
                    ) {
                      removePoll.mutate(p.id);
                    }
                  }}
                  disabled={removePoll.isPending}
                  className="min-h-11 min-w-11 rounded-md bg-status-busy/15 px-2 text-xs text-status-busy disabled:opacity-40"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </SubScreen>
  );
}

function TickEditor({
  initial,
  isPending,
  onSave,
}: {
  initial: number;
  isPending: boolean;
  onSave: (v: number) => void;
}) {
  const [val, setVal] = useState(initial.toString());
  useEffect(() => {
    setVal(initial.toString());
  }, [initial]);
  const parsed = parseInt(val, 10);
  const valid = !Number.isNaN(parsed) && parsed >= 1 && parsed <= 120;
  const dirty = valid && parsed !== initial;

  return (
    <div className="flex items-center gap-2">
      <input
        type="text"
        inputMode="numeric"
        value={val}
        onChange={(e) => setVal(e.target.value.replace(/[^0-9]/g, ""))}
        className="w-20 rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text text-center tabular-nums outline-none border border-transparent focus:border-tg-link"
      />
      <div className="text-xs text-tg-hint">мин (1..120)</div>
      <button
        type="button"
        disabled={!dirty || isPending}
        onClick={() => onSave(parsed)}
        className="ml-auto min-h-11 rounded-md bg-tg-link/15 px-3 text-xs text-tg-link disabled:opacity-40"
      >
        {isPending ? "..." : "Сохранить"}
      </button>
    </div>
  );
}
