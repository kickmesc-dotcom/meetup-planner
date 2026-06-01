import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  avatarsScheduleOnceDelete,
  avatarsScheduleOnceGet,
  avatarsScheduleOncePost,
  avatarsSyncNow,
  closeAdminPoll,
  deleteAdminPoll,
  fetchAdminPolls,
  fetchPollsDefaults,
  fetchScheduledSettings,
  updatePollsDefaults,
  updateScheduledSettings,
  type PollsDefaults,
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

interface Props {
  onBack: () => void;
}

export default function ScheduledPublicationsScreen({ onBack }: Props) {
  const qc = useQueryClient();

  // GHG6 M6: блок очереди задач вынесен в отдельный экран JobsQueueScreen
  // (доступен из AdminScreen → «📋 Очередь задач»). Здесь больше нет hot-mode
  // и polling'а /admin/jobs.

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
      // Invalidate jobs cache на случай, если из JobsQueueScreen он уже подгружен.
      qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
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
            icon="👑"
            title="Лох дня"
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
            <AvatarsActions
              onJobsChanged={() =>
                qc.invalidateQueries({ queryKey: ["admin", "jobs"] })
              }
            />
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

          {/* GHG7 P2.3.f: «Реакции бота» вынесены в отдельный экран
              BotReactionsScreen (меню админки → «🤖 Реакции»). */}

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

      {/* GHG6 M6 (п.17): «Очередь задач» вынесена в отдельный экран
          `JobsQueueScreen`, доступный из AdminScreen сразу под «🌐 Прокси»
          с возможностью reschedule/skip-next. Здесь её больше нет. */}

      {/* G2.10 + G3.6: единый блок настроек опросов в чате — pin_default,
          quorum_auto_close + live_participants_count, pin_result. */}
      <PollsDefaultsBlock />

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
 * GHG6 G2.10 + G3.6: дефолты опросов в чате.
 *
 * Один блок, четыре поля, авто-save на debounce 500ms по `dirty`. Отдельный
 * REST endpoint (`/admin/polls/defaults`), независимый от ScheduledSettings —
 * это не «расписание», а персистентные настройки поведения при
 * создании/закрытии опросов.
 *
 * Поля:
 * - `pin_default` (Switch) — пинить ли при публикации (G2). Чекбокс в
 *   `GamesScreen/PollSheet` тоже отправляет своё значение, но если в payload
 *   `pin=null` — сервер берёт этот дефолт.
 * - `quorum_auto_close` (Switch) — стопать ли опрос при N уникальных голосах.
 * - `live_participants_count` (NumberInput) — N для предыдущего. Disabled,
 *   когда quorum_auto_close=false, чтобы значение не вводило в заблуждение.
 * - `pin_result` (Switch) — пинить ли announce-сообщение с результатами.
 */
function PollsDefaultsBlock() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "polls-defaults"],
    queryFn: fetchPollsDefaults,
    staleTime: 60_000,
  });

  const [draft, setDraft] = useState<PollsDefaults | null>(null);
  useEffect(() => {
    if (q.data) setDraft({ ...q.data });
  }, [q.data]);

  const save = useMutation({
    mutationFn: updatePollsDefaults,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "polls-defaults"], data);
    },
    onError: errAlert,
  });

  // Auto-save: каждое изменение draft'а (после задержки 500мс) уходит на бэк.
  // Меньше кнопок «Сохранить» — UI становится плотнее. Если save в полёте,
  // следующий schedule перетрёт текущий timeout — последняя версия победит.
  const draftRef = useRef(draft);
  draftRef.current = draft;
  useEffect(() => {
    if (!draft || !q.data) return;
    const same =
      draft.pin_default === q.data.pin_default &&
      draft.quorum_auto_close === q.data.quorum_auto_close &&
      draft.live_participants_count === q.data.live_participants_count &&
      draft.pin_result === q.data.pin_result;
    if (same) return;
    const t = setTimeout(() => {
      const cur = draftRef.current;
      if (cur) save.mutate(cur);
    }, 500);
    return () => clearTimeout(t);
  }, [draft, q.data, save]);

  if (q.isPending || !draft) {
    return (
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">📌 Дефолты опросов в чате</div>
        <ListSkeleton rows={3} />
      </section>
    );
  }

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-base font-semibold">📌 Дефолты опросов в чате</div>
        {save.isPending && <Spinner />}
      </div>
      <div className="text-[11px] text-tg-hint">
        Пин и автозакрытие применяются к опросам из приложения (Games + PollSheet)
        и zaebal-voting. Если в форме создания опроса оставить чекбокс «закрепить»
        пустым — берётся значение отсюда.
      </div>

      {/* G2.10 — Пин при публикации */}
      <DefaultsRow
        label="📌 Закреплять опросы при публикации"
        hint="Bot.pin_chat_message с disable_notification=true сразу после публикации."
      >
        <Switch
          checked={draft.pin_default}
          onChange={(v) => {
            haptic("selection");
            setDraft({ ...draft, pin_default: v });
          }}
        />
      </DefaultsRow>

      {/* G3.6 — Авто-закрытие по кворуму */}
      <DefaultsRow
        label="⏱ Авто-закрытие по кворуму"
        hint="Бот зовёт stop_poll, когда N уникальных голосов набрано."
      >
        <Switch
          checked={draft.quorum_auto_close}
          onChange={(v) => {
            haptic("selection");
            setDraft({ ...draft, quorum_auto_close: v });
          }}
        />
      </DefaultsRow>

      <DefaultsRow
        label="N живых участников"
        hint="Сколько уникальных голосов = «все живые». 1–10."
      >
        <input
          type="number"
          min={1}
          max={10}
          value={draft.live_participants_count}
          disabled={!draft.quorum_auto_close}
          onChange={(e) => {
            const n = Math.max(1, Math.min(10, parseInt(e.target.value, 10) || 1));
            setDraft({ ...draft, live_participants_count: n });
          }}
          className="w-16 rounded-md bg-tg-bg/70 px-2 py-1 text-sm text-tg-text disabled:opacity-40"
        />
      </DefaultsRow>

      {/* G3.6 — Пин announce-сообщения */}
      <DefaultsRow
        label="📍 Закреплять сообщение с результатами"
        hint="После закрытия опроса announce-сообщение с победителем уходит в закреп."
      >
        <Switch
          checked={draft.pin_result}
          onChange={(v) => {
            haptic("selection");
            setDraft({ ...draft, pin_result: v });
          }}
        />
      </DefaultsRow>
    </section>
  );
}

function DefaultsRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="text-sm text-tg-text">{label}</div>
        <div className="text-[11px] text-tg-hint">{hint}</div>
      </div>
      {children}
    </div>
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
