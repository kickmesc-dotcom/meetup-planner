/**
 * GHG6 M5/M6: отдельный экран «📋 Очередь задач».
 *
 * По п.17 — пользователь хочет видеть запланированные задачи поближе к топу
 * (сразу под Прокси) и иметь возможность вручную:
 *   1) поменять время ближайшего запуска (POST /admin/jobs/{id}/reschedule);
 *   2) отменить ближайший запуск (DELETE /admin/jobs/{id}):
 *      - для recurring (interval/cron) — пропуск ближайшего, scheduler сам
 *        проставит следующий по триггеру;
 *      - для one-shot (date) — реально удалить job;
 *      - для reminder — пометить sent_at=now (старая семантика).
 *
 * Не editable (proxy_health) рендерится только как информация — без кнопок.
 */
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";

import {
  cancelScheduledJob,
  fetchScheduledJobs,
  rescheduleScheduledJob,
  type ScheduledJob,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import { haptic, showAlert } from "@/tg/webapp";
import SubScreen from "./SubScreen";

const JOBS_IDLE_INTERVAL_MS = 10 * 60_000;
const JOBS_HOT_INTERVAL_MS = 5_000;
const JOBS_HOT_DURATION_MS = 3 * 60_000;

interface Props {
  onBack: () => void;
}

export default function JobsQueueScreen({ onBack }: Props) {
  const qc = useQueryClient();
  const [jobsHotUntil, setJobsHotUntil] = useState(0);
  const hotTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const enterHotMode = () => {
    setJobsHotUntil(Date.now() + JOBS_HOT_DURATION_MS);
    if (hotTimerRef.current) clearTimeout(hotTimerRef.current);
    hotTimerRef.current = setTimeout(() => setJobsHotUntil(0), JOBS_HOT_DURATION_MS);
  };
  useEffect(() => () => {
    if (hotTimerRef.current) clearTimeout(hotTimerRef.current);
  }, []);

  const isHot = Date.now() < jobsHotUntil;
  const interval = isHot ? JOBS_HOT_INTERVAL_MS : JOBS_IDLE_INTERVAL_MS;

  const jobs = useQuery({
    queryKey: ["admin", "jobs"],
    queryFn: fetchScheduledJobs,
    refetchInterval: interval,
  });

  const errAlert = (e: unknown) => {
    haptic("error");
    void showAlert(humanizeApiError(e));
  };

  const cancel = useMutation({
    mutationFn: (id: string) => cancelScheduledJob(id),
    onSuccess: () => {
      haptic("light");
      enterHotMode();
      qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
    },
    onError: errAlert,
  });

  const reschedule = useMutation({
    mutationFn: ({ id, runAtIso }: { id: string; runAtIso: string }) =>
      rescheduleScheduledJob(id, runAtIso),
    onSuccess: () => {
      haptic("success");
      enterHotMode();
      qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
    },
    onError: errAlert,
  });

  return (
    <SubScreen
      title="📋 Очередь задач"
      subtitle="APScheduler-job'ы + напоминания встреч"
      onBack={onBack}
    >
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="flex items-start justify-between gap-2 mb-1">
          <div className="text-base font-semibold">📋 Очередь</div>
          <button
            type="button"
            onClick={() => {
              haptic("light");
              enterHotMode();
              jobs.refetch();
            }}
            className="shrink-0 rounded-md bg-tg-bg/70 px-2 py-1 text-[10px] text-tg-hint active:scale-95 transition-transform"
            title="Обновить и опрашивать чаще 3 минуты"
          >
            ↻ {isHot ? "тик 5с" : "тик 10м"}
          </button>
        </div>
        <div className="text-xs text-tg-hint mb-2">
          ✎ — подвинуть время ближайшего запуска. 🚫 — пропустить ближайший
          запуск (recurring остаётся, one-shot/reminder удаляются).
        </div>
        {jobs.isPending ? (
          <ListSkeleton rows={4} />
        ) : (jobs.data ?? []).length === 0 ? (
          <div className="text-xs text-tg-hint">Очередь пуста.</div>
        ) : (
          <div className="space-y-1.5">
            {(jobs.data ?? []).map((j) => (
              <JobRow
                key={j.id}
                job={j}
                pending={cancel.isPending || reschedule.isPending}
                onCancel={() => {
                  if (
                    confirm(
                      j.trigger_kind === "date" || j.kind === "reminder"
                        ? `Удалить «${j.label}»?`
                        : `Пропустить ближайший запуск «${j.label}»?`,
                    )
                  ) {
                    cancel.mutate(j.id);
                  }
                }}
                onReschedule={(iso) => reschedule.mutate({ id: j.id, runAtIso: iso })}
              />
            ))}
          </div>
        )}
      </section>
    </SubScreen>
  );
}

function JobRow({
  job,
  pending,
  onCancel,
  onReschedule,
}: {
  job: ScheduledJob;
  pending: boolean;
  onCancel: () => void;
  onReschedule: (utcIso: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [localValue, setLocalValue] = useState<string>(() => toLocalInput(job.next_run_at));

  useEffect(() => {
    setLocalValue(toLocalInput(job.next_run_at));
  }, [job.next_run_at]);

  // editable=undefined у старых серверов → считаем true (обратная совместимость).
  const editable = job.editable !== false;
  const kindLabel =
    job.trigger_kind ?? (job.kind as ScheduledJob["trigger_kind"]) ?? "unknown";
  const cancelLabel =
    kindLabel === "date" || job.kind === "reminder" ? "🚫" : "⏭";
  const cancelTitle =
    kindLabel === "date" || job.kind === "reminder"
      ? "Удалить"
      : "Пропустить ближайший запуск";

  return (
    <div className="rounded-lg bg-tg-bg/50 px-2 py-1.5">
      <div className="flex items-center gap-2">
        <div className="flex-1 min-w-0">
          <div className="text-sm truncate text-tg-text">{job.label}</div>
          <div className="text-[10px] text-tg-hint truncate">
            {job.next_run_at
              ? format(new Date(job.next_run_at), "dd.MM HH:mm")
              : "—"}
            {job.detail && ` · ${job.detail}`}
          </div>
        </div>
        <div
          className={[
            "text-[10px] rounded-full px-1.5 py-0.5 shrink-0",
            kindLabel === "reminder"
              ? "bg-status-maybe/15 text-status-maybe"
              : kindLabel === "date"
              ? "bg-status-busy/15 text-status-busy"
              : "bg-tg-link/15 text-tg-link",
          ].join(" ")}
        >
          {kindLabel}
        </div>
        {editable && (
          <>
            <button
              type="button"
              onClick={() => {
                haptic("light");
                setEditing((v) => !v);
              }}
              disabled={pending}
              className="min-h-11 min-w-11 rounded-md bg-tg-bg/70 px-2 text-xs text-tg-text border border-tg-hint/30 disabled:opacity-40"
              title="Изменить время"
            >
              ✎
            </button>
            <button
              type="button"
              onClick={onCancel}
              disabled={pending}
              className="min-h-11 min-w-11 rounded-md bg-status-busy/15 px-2 text-xs text-status-busy disabled:opacity-40 inline-flex items-center justify-center"
              title={cancelTitle}
            >
              {pending ? <Spinner /> : cancelLabel}
            </button>
          </>
        )}
      </div>
      {editing && editable && (
        <div className="mt-2 flex items-center gap-2">
          <input
            type="datetime-local"
            value={localValue}
            onChange={(e) => setLocalValue(e.target.value)}
            className="flex-1 rounded-md bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
          />
          <button
            type="button"
            onClick={() => {
              const iso = fromLocalInput(localValue);
              if (!iso) {
                void showAlert("Некорректное время");
                return;
              }
              haptic("medium");
              setEditing(false);
              onReschedule(iso);
            }}
            disabled={pending}
            className="min-h-11 rounded-md bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform"
          >
            💾
          </button>
        </div>
      )}
    </div>
  );
}

/** ISO → 'YYYY-MM-DDTHH:mm' в локальной зоне (для <input type="datetime-local">). */
function toLocalInput(iso: string | null): string {
  if (!iso) {
    const now = new Date();
    return formatLocal(now);
  }
  return formatLocal(new Date(iso));
}

function formatLocal(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** datetime-local (локальная зона) → UTC ISO. Возвращает null на пустоту. */
function fromLocalInput(v: string): string | null {
  if (!v) return null;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}
