import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  cancelScheduledJob,
  closeAdminPoll,
  deleteAdminPoll,
  fetchAdminPolls,
  fetchScheduledJobs,
  fetchScheduledSettings,
  updateScheduledSettings,
  type ScheduledSettingsIO,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";

const errAlert = (e: unknown) => {
  haptic("error");
  void showAlert(humanizeApiError(e));
};

const JOBS_IDLE_INTERVAL_MS = 10 * 60 * 1000;
const JOBS_HOT_INTERVAL_MS = 5_000;
const JOBS_HOT_DURATION_MS = 3 * 60 * 1000;

const WEEKDAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

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

  const sched = useQuery({
    queryKey: ["admin", "scheduled"],
    queryFn: fetchScheduledSettings,
  });

  const [draft, setDraft] = useState<ScheduledSettingsIO | null>(null);
  useEffect(() => {
    if (sched.data) setDraft(structuredClone(sched.data));
  }, [sched.data]);

  const dirty = useMemo(
    () => !!draft && !!sched.data && JSON.stringify(draft) !== JSON.stringify(sched.data),
    [draft, sched.data],
  );

  const save = useMutation({
    mutationFn: updateScheduledSettings,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "scheduled"], data);
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

  const patch = useCallback(
    (updater: (d: ScheduledSettingsIO) => ScheduledSettingsIO) => {
      setDraft((cur) => (cur ? updater(structuredClone(cur)) : cur));
    },
    [],
  );

  return (
    <SubScreen
      title="⏱️ Запланированные публикации"
      subtitle="Master-toggles, очередь задач, опросы в чате"
      onBack={onBack}
    >
      {sched.isPending || !draft ? (
        <ListSkeleton rows={6} />
      ) : (
        <>
          <ToggleBlock
            icon="⏰"
            title="Тик напоминаний"
            hint="Раз в N минут бот проверяет очередь напоминаний к встречам."
            enabled={draft.reminders.enabled}
            onToggle={(v) =>
              patch((d) => {
                d.reminders.enabled = v;
                return d;
              })
            }
          >
            <Field label="Интервал, мин (1–120)">
              <NumberInput
                value={draft.reminders.tick_minutes}
                min={1}
                max={120}
                onChange={(v) =>
                  patch((d) => {
                    d.reminders.tick_minutes = v;
                    return d;
                  })
                }
              />
            </Field>
          </ToggleBlock>

          <ToggleBlock
            icon="🤡"
            title="Автолох"
            hint="Бот сам выбирает лоха в течение рабочего окна."
            enabled={draft.loser.enabled}
            onToggle={(v) =>
              patch((d) => {
                d.loser.enabled = v;
                return d;
              })
            }
          >
            <Field label="Раз в сутки (1–12)">
              <NumberInput
                value={draft.loser.per_day}
                min={1}
                max={12}
                onChange={(v) =>
                  patch((d) => {
                    d.loser.per_day = v;
                    return d;
                  })
                }
              />
            </Field>
            <Field label="Окно активности">
              <HourRange
                start={draft.loser.window_start_hour}
                end={draft.loser.window_end_hour}
                onChange={(s, e) =>
                  patch((d) => {
                    d.loser.window_start_hour = s;
                    d.loser.window_end_hour = e;
                    return d;
                  })
                }
              />
            </Field>
          </ToggleBlock>

          <ToggleBlock
            icon="💬"
            title="Рандомная фраза"
            hint="Автопостинг рандомных фраз. Окно — когда бот может постить."
            enabled={draft.phrases.enabled}
            onToggle={(v) =>
              patch((d) => {
                d.phrases.enabled = v;
                return d;
              })
            }
          >
            <Field label="Окно активности">
              <HhmmRange
                start={draft.phrases.window_start}
                end={draft.phrases.window_end}
                onChange={(s, e) =>
                  patch((d) => {
                    d.phrases.window_start = s;
                    d.phrases.window_end = e;
                    return d;
                  })
                }
              />
            </Field>
          </ToggleBlock>

          <ToggleBlock
            icon="🖼️"
            title="Синхронизация аватарок"
            hint="Бот скачивает свежие аватарки участников из Telegram."
            enabled={draft.avatars.enabled}
            onToggle={(v) =>
              patch((d) => {
                d.avatars.enabled = v;
                return d;
              })
            }
          >
            <Field label="Раз в сутки (мин 0.14 ≈ раз в неделю)">
              <NumberInput
                value={draft.avatars.per_day}
                min={0.14}
                max={24}
                step={0.1}
                onChange={(v) =>
                  patch((d) => {
                    d.avatars.per_day = v;
                    return d;
                  })
                }
              />
            </Field>
          </ToggleBlock>

          <ToggleBlock
            icon="🎂"
            title="Дни рождения"
            hint="Все напоминания о ДР (диапазон-перед-днём — в экране ДР)."
            enabled={draft.birthdays.alerts_enabled}
            onToggle={(v) =>
              patch((d) => {
                d.birthdays.alerts_enabled = v;
                return d;
              })
            }
          />

          <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-base">💩</span>
              <span className="text-base font-semibold">Чухан недели</span>
            </div>
            <div className="text-xs text-tg-hint mb-2">
              День недели и окно, в котором бот публикует чухана.
            </div>
            <Field label="День недели">
              <div className="flex flex-wrap gap-1">
                {WEEKDAYS_RU.map((label, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      haptic("selection");
                      patch((d) => {
                        d.chukhan.weekday = idx;
                        return d;
                      });
                    }}
                    className={[
                      "min-h-9 min-w-9 rounded-md px-2 text-xs",
                      draft.chukhan.weekday === idx
                        ? "bg-tg-button text-tg-button-text"
                        : "bg-tg-bg/70 text-tg-text",
                    ].join(" ")}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </Field>
            <Field label="Окно активности">
              <HhmmRange
                start={draft.chukhan.window_start}
                end={draft.chukhan.window_end}
                onChange={(s, e) =>
                  patch((d) => {
                    d.chukhan.window_start = s;
                    d.chukhan.window_end = e;
                    return d;
                  })
                }
              />
            </Field>
          </section>

          <div className="sticky bottom-0 -mx-3 px-3 pb-3 pt-2 bg-tg-bg/95 backdrop-blur">
            <button
              type="button"
              disabled={!dirty || save.isPending}
              onClick={() => {
                if (!draft) return;
                haptic("medium");
                save.mutate(draft);
              }}
              className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
            >
              {save.isPending && <Spinner />}
              {save.isPending
                ? "Сохраняем…"
                : dirty
                ? "💾 Сохранить настройки"
                : "✓ Сохранено"}
            </button>
          </div>
        </>
      )}

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

function ToggleBlock({
  icon,
  title,
  hint,
  enabled,
  onToggle,
  children,
}: {
  icon: string;
  title: string;
  hint: string;
  enabled: boolean;
  onToggle: (v: boolean) => void;
  children?: ReactNode;
}) {
  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-base">{icon}</span>
          <div className="min-w-0">
            <div className="text-base font-semibold text-tg-text">{title}</div>
            <div className="text-[11px] text-tg-hint">{hint}</div>
          </div>
        </div>
        <Switch
          checked={enabled}
          onChange={(v) => {
            haptic("selection");
            onToggle(v);
          }}
        />
      </div>
      {enabled && children && <div className="mt-2 space-y-2">{children}</div>}
    </section>
  );
}

function Switch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] text-tg-hint mb-1">{label}</div>
      {children}
    </div>
  );
}

function NumberInput({
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => {
    setDraft(String(value));
  }, [value]);
  const isInt = step >= 1 && Number.isInteger(step);
  return (
    <input
      type="text"
      inputMode={isInt ? "numeric" : "decimal"}
      value={draft}
      onChange={(e) => {
        const cleaned = e.target.value.replace(isInt ? /[^0-9]/g : /[^0-9.]/g, "");
        setDraft(cleaned);
      }}
      onBlur={() => {
        const n = parseFloat(draft);
        if (Number.isNaN(n)) {
          setDraft(String(value));
          return;
        }
        const clamped = Math.max(min, Math.min(max, n));
        const rounded = isInt ? Math.round(clamped) : Math.round(clamped * 100) / 100;
        setDraft(String(rounded));
        if (rounded !== value) onChange(rounded);
      }}
      className="w-24 rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text text-center tabular-nums outline-none border border-transparent focus:border-tg-link"
    />
  );
}

function HourRange({
  start,
  end,
  onChange,
}: {
  start: number;
  end: number;
  onChange: (s: number, e: number) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <NumberInput
        value={start}
        min={0}
        max={23}
        onChange={(v) => onChange(v, end)}
      />
      <span className="text-tg-hint text-xs">…</span>
      <NumberInput
        value={end}
        min={0}
        max={23}
        onChange={(v) => onChange(start, v)}
      />
      <span className="text-tg-hint text-xs">ч</span>
    </div>
  );
}

function HhmmRange({
  start,
  end,
  onChange,
}: {
  start: string;
  end: string;
  onChange: (s: string, e: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <input
        type="time"
        value={start}
        onChange={(e) => onChange(e.target.value, end)}
        className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
      />
      <span className="text-tg-hint text-xs">…</span>
      <input
        type="time"
        value={end}
        onChange={(e) => onChange(start, e.target.value)}
        className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
      />
    </div>
  );
}
