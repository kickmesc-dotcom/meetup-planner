import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  avatarsScheduleOnceDelete,
  avatarsScheduleOnceGet,
  avatarsScheduleOncePost,
  avatarsSyncNow,
  cancelScheduledJob,
  closeAdminPoll,
  deleteAdminPoll,
  fetchAdminPolls,
  fetchBotReactions,
  fetchScheduledJobs,
  fetchScheduledSettings,
  updateBotReactions,
  updateScheduledSettings,
  type BotReactionsSettings,
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
          {/* GHG6 H3 (п.16): числовые/временные поля переехали в отдельный
              экран «🎛 Интервалы и окна». Здесь — только master-toggles. */}
          <ToggleBlock
            icon="⏰"
            title="Тик напоминаний"
            hint="Раз в N минут бот проверяет очередь. Интервал — в «Интервалы и окна»."
            enabled={draft.reminders.enabled}
            onToggle={(v) =>
              patch((d) => {
                d.reminders.enabled = v;
                return d;
              })
            }
          />

          <ToggleBlock
            icon="🤡"
            title="Автолох"
            hint="Бот сам выбирает лоха. Частота и окно — в «Интервалы и окна»."
            enabled={draft.loser.enabled}
            onToggle={(v) =>
              patch((d) => {
                d.loser.enabled = v;
                return d;
              })
            }
          />

          <ToggleBlock
            icon="💬"
            title="Рандомная фраза"
            hint="Автопостинг рандомных фраз. Окно — в «Интервалы и окна»."
            enabled={draft.phrases.enabled}
            onToggle={(v) =>
              patch((d) => {
                d.phrases.enabled = v;
                return d;
              })
            }
          />

          <ToggleBlock
            icon="🖼️"
            title="Синхронизация аватарок"
            hint="Регулярного авто-синхрона больше нет. Запускай вручную или планируй на конкретное время."
            enabled={draft.avatars.enabled}
            onToggle={(v) =>
              patch((d) => {
                d.avatars.enabled = v;
                return d;
              })
            }
          >
            <AvatarsActions onJobsChanged={enterHotMode} />
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

          <BotReactionsSection />

          {/* GHG6 H3 (п.16): расписание чухана (day + window) переехало в
              «🎛 Интервалы и окна». Master-toggle'a у чухана нет — он публикуется
              всегда, когда наступает окно. */}

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

/**
 * GHG6 E9: три master-toggle реакций бота. Отдельная секция со своим
 * локальным state и save-mutation (не делит draft с ScheduledSettingsIO,
 * чтобы не плодить лишние поля в общей форме).
 */
function BotReactionsSection() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "bot-reactions"],
    queryFn: fetchBotReactions,
  });
  const [draft, setDraft] = useState<BotReactionsSettings | null>(null);
  useEffect(() => {
    if (q.data) setDraft({ ...q.data });
  }, [q.data]);

  const save = useMutation({
    mutationFn: updateBotReactions,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "bot-reactions"], data);
    },
    onError: errAlert,
  });

  if (q.isPending || !draft) {
    return (
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <ListSkeleton rows={3} />
      </section>
    );
  }

  const setField = (key: keyof BotReactionsSettings, v: boolean) => {
    const next = { ...draft, [key]: v };
    setDraft(next);
    save.mutate(next);
  };

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-base">🤖</span>
        <span className="text-base font-semibold">Реакции бота</span>
      </div>
      <div className="text-xs text-tg-hint mb-2">
        Бот отвечает рандомной шизо-цитатой на упоминание и/или reply.
      </div>

      <div className="flex items-start justify-between gap-2 rounded-md bg-tg-bg/40 px-2 py-2">
        <div className="min-w-0">
          <div className="text-sm text-tg-text">@-упоминание</div>
          <div className="text-[11px] text-tg-hint">
            На тег <code>@бот</code> бот отвечает фразой.
          </div>
        </div>
        <Switch
          checked={draft.mention_enabled}
          onChange={(v) => {
            haptic("selection");
            setField("mention_enabled", v);
          }}
        />
      </div>

      <div className="flex items-start justify-between gap-2 rounded-md bg-tg-bg/40 px-2 py-2">
        <div className="min-w-0">
          <div className="text-sm text-tg-text">Reply на любое сообщение бота</div>
          <div className="text-[11px] text-tg-hint">
            На любой ответ-реплай на сообщение бота — бот отвечает фразой
            (включая reply к собственным цитатам).
          </div>
        </div>
        <Switch
          checked={draft.reply_all_enabled}
          onChange={(v) => {
            haptic("selection");
            setField("reply_all_enabled", v);
          }}
        />
      </div>

      <div className="flex items-start justify-between gap-2 rounded-md bg-tg-bg/40 px-2 py-2">
        <div className="min-w-0">
          <div className="text-sm text-tg-text">Reply, кроме рандом-цитат</div>
          <div className="text-[11px] text-tg-hint">
            Бот отвечает на reply к своим сообщениям, кроме случаев, когда
            оригинал — рандом-цитата. Работает независимо от верхнего тогла.
          </div>
        </div>
        <Switch
          checked={draft.reply_except_phrases_enabled}
          onChange={(v) => {
            haptic("selection");
            setField("reply_except_phrases_enabled", v);
          }}
        />
      </div>
    </section>
  );
}

/**
 * GHG6 E10: ручные операции с синхронизацией аватарок.
 * Рекуррентного расписания больше нет — только разовая кнопка и опц.
 * однократный запуск на конкретное datetime.
 */
function AvatarsActions({ onJobsChanged }: { onJobsChanged: () => void }) {
  const qc = useQueryClient();
  const sched = useQuery({
    queryKey: ["admin", "avatars-schedule-once"],
    queryFn: avatarsScheduleOnceGet,
    staleTime: 10_000,
  });

  // Дефолт: завтра 10:00 локально. Формат для <input type="datetime-local">.
  const [whenLocal, setWhenLocal] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(10, 0, 0, 0);
    // datetime-local требует YYYY-MM-DDTHH:mm
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  });

  const syncNow = useMutation({
    mutationFn: avatarsSyncNow,
    onSuccess: (res) => {
      haptic("success");
      void showAlert(`Готово. Запрошены аватарки ${res.synced} пользователей.`);
      qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: errAlert,
  });

  const schedule = useMutation({
    mutationFn: (iso: string) => avatarsScheduleOncePost(iso),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "avatars-schedule-once"], data);
      onJobsChanged();
    },
    onError: errAlert,
  });

  const cancel = useMutation({
    mutationFn: avatarsScheduleOnceDelete,
    onSuccess: (data) => {
      haptic("warning");
      qc.setQueryData(["admin", "avatars-schedule-once"], data);
      onJobsChanged();
    },
    onError: errAlert,
  });

  const scheduledRunAt = sched.data?.scheduled ? sched.data.run_at : null;

  return (
    <div className="space-y-2">
      <button
        type="button"
        disabled={syncNow.isPending}
        onClick={() => {
          haptic("medium");
          syncNow.mutate();
        }}
        className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-50 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
      >
        {syncNow.isPending && <Spinner />}
        🔄 Синхронизировать сейчас
      </button>

      <div className="rounded-lg bg-tg-bg/40 p-2 space-y-2">
        <div className="text-[11px] text-tg-hint">
          📅 Запланировать однократно
        </div>
        <input
          type="datetime-local"
          value={whenLocal}
          onChange={(e) => setWhenLocal(e.target.value)}
          className="w-full rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
        />
        <button
          type="button"
          disabled={schedule.isPending || !whenLocal}
          onClick={() => {
            // datetime-local — без таймзоны; интерпретируем как локальное время
            // и шлём как ISO. Backend парсит и считает naive→UTC (см. _parse_iso_future).
            const local = new Date(whenLocal);
            if (Number.isNaN(local.getTime())) {
              errAlert(new Error("invalid_datetime"));
              return;
            }
            haptic("medium");
            schedule.mutate(local.toISOString());
          }}
          className="w-full min-h-11 rounded-lg bg-tg-link/15 py-2 text-sm font-medium text-tg-link disabled:opacity-50 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
        >
          {schedule.isPending && <Spinner />}
          📅 Запланировать
        </button>
        {scheduledRunAt && (
          <div className="flex items-center gap-2 rounded-md bg-tg-bg/60 px-2 py-1.5 text-[11px]">
            <div className="flex-1 text-tg-text">
              Запланировано: {format(new Date(scheduledRunAt), "dd.MM.yyyy HH:mm")}
            </div>
            <button
              type="button"
              disabled={cancel.isPending}
              onClick={() => {
                if (confirm("Отменить запланированную синхронизацию?")) {
                  cancel.mutate();
                }
              }}
              className="min-h-9 rounded-md bg-status-busy/15 px-2 text-status-busy disabled:opacity-50"
            >
              ✕
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
