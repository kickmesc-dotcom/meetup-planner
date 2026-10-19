import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { humanizeApiError } from "@/api/client";
import {
  cancelNotification,
  fetchEmployeesPool,
  fetchNotificationsCenter,
  muteAllNotifications,
  postponePendingNotification,
  resetPendingNotification,
  sendNotification,
  skipPendingNotification,
} from "@/api/hrOps";
import { ListSkeleton } from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import SubScreen from "./SubScreen";

/**
 * Центр уведомлений (админ): что уже ушло и что ещё сработает.
 *
 * Два разных ответа на «а что там с уведомлениями»:
 *  • отправленные — по людям, с возможностью убрать конкретное;
 *  • запланированные — кому и во сколько уйдёт напоминание о сроке и вторая
 *    ступень эскалации.
 *
 * Мьют один и общий: он глушит доставку в Telegram, а уведомления внутри
 * приложения продолжают копиться — иначе утренний разбор потерялся бы.
 * Об этом честно написано под кнопками.
 */
export default function NotificationsScreen({ onBack }: { onBack: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "notifications"],
    queryFn: fetchNotificationsCenter,
    staleTime: 15_000,
  });
  const pool = useQuery({
    queryKey: ["admin", "employees-pool"],
    queryFn: fetchEmployeesPool,
    staleTime: 60_000,
  });

  const [target, setTarget] = useState<number | null>(null);
  const [text, setText] = useState("");
  /** По какому поручению сейчас выбираем, на сколько сдвинуть напоминание. */
  const [moving, setMoving] = useState<number | null>(null);

  const refresh = () =>
    void qc.invalidateQueries({ queryKey: ["admin", "notifications"] });

  const mute = useMutation({
    mutationFn: (hours: number) => muteAllNotifications(hours),
    onSuccess: () => {
      haptic("success");
      refresh();
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const drop = useMutation({
    mutationFn: (id: number) => cancelNotification(id),
    onSuccess: () => {
      haptic("success");
      refresh();
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const move = useMutation({
    mutationFn: (input: { taskId: number; minutes: number }) =>
      postponePendingNotification(input.taskId, input.minutes),
    onSuccess: () => {
      haptic("success");
      setMoving(null);
      refresh();
    },
    onError: (error) => {
      setMoving(null);
      void showAlert(humanizeApiError(error));
    },
  });

  const skip = useMutation({
    mutationFn: (taskId: number) => skipPendingNotification(taskId),
    onSuccess: () => {
      haptic("success");
      refresh();
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const restore = useMutation({
    mutationFn: (taskId: number) => resetPendingNotification(taskId),
    onSuccess: () => {
      haptic("success");
      refresh();
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const send = useMutation({
    mutationFn: () => sendNotification(target as number, text.trim()),
    onSuccess: () => {
      haptic("success");
      setText("");
      refresh();
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const muted = q.data?.muted_until ?? null;
  const people = (pool.data?.items ?? []).filter(
    (card) => card.is_active && card.fired_at === null,
  );

  const muteAll = async (hours: number, label: string) => {
    haptic("medium");
    const first = await showConfirm(
      `Замьютить все алерты в чат на ${label}?\n\nВ приложении уведомления продолжат копиться.`,
    );
    if (!first) return;
    const second = await showConfirm(
      "Подтверди ещё раз: пока мьют активен, бот молчит про сроки и просрочки.",
    );
    if (!second) return;
    mute.mutate(hours);
  };

  return (
    <SubScreen
      title="🔔 Уведомления"
      subtitle="Что ушло и что запланировано"
      onBack={onBack}
    >
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-sm font-semibold text-tg-text">Мьют алертов</div>
        <p className="mt-1 text-[11px] text-tg-hint">
          {muted
            ? `Чат молчит до ${formatMoment(muted)}.`
            : "Алерты в чат идут как обычно."}
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {[
            { label: "24 ч", hours: 24 },
            { label: "3 дня", hours: 72 },
            { label: "7 дней", hours: 168 },
            { label: "30 дней", hours: 720 },
          ].map((option) => (
            <button
              key={option.hours}
              type="button"
              disabled={mute.isPending}
              onClick={() => void muteAll(option.hours, option.label)}
              className="min-h-9 rounded-full bg-tg-bg/60 px-3 text-xs text-tg-text disabled:opacity-50"
            >
              На {option.label}
            </button>
          ))}
          {muted && (
            <button
              type="button"
              disabled={mute.isPending}
              onClick={() => {
                haptic("selection");
                mute.mutate(0);
              }}
              className="min-h-9 rounded-full bg-status-busy/15 px-3 text-xs text-status-busy disabled:opacity-50"
            >
              Снять мьют
            </button>
          )}
        </div>
        <p className="mt-2 text-[10px] text-tg-hint">
          Мьют глушит доставку в Telegram: в приложении уведомления продолжают
          копиться, поэтому утренний разбор не потеряется.
        </p>
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-sm font-semibold text-tg-text">
          Написать сотруднику
        </div>
        <p className="mt-1 text-[11px] text-tg-hint">
          Личное уведомление в приложение. В чат не дублируем.
        </p>
        <select
          aria-label="Кому отправить уведомление"
          value={target ?? ""}
          onChange={(event) =>
            setTarget(event.target.value ? Number(event.target.value) : null)
          }
          className="mt-2 min-h-9 w-full rounded-lg bg-tg-bg/60 px-2 text-xs text-tg-text"
        >
          <option value="">Выбери сотрудника</option>
          {people.map((card) => (
            <option key={card.employee_id} value={card.employee_id}>
              {card.display_name}
              {card.position ?? card.badge ? ` · ${card.position ?? card.badge}` : ""}
            </option>
          ))}
        </select>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={2}
          maxLength={400}
          placeholder="Что сказать сотруднику"
          className="mt-2 w-full rounded-lg bg-tg-bg/60 p-2 text-sm text-tg-text placeholder:text-tg-hint"
        />
        <button
          type="button"
          disabled={target === null || text.trim().length === 0 || send.isPending}
          onClick={() => {
            haptic("medium");
            send.mutate();
          }}
          className="mt-2 min-h-10 w-full rounded-lg bg-tg-button text-xs font-medium text-tg-button-text disabled:opacity-50"
        >
          Отправить
        </button>
      </section>

      {q.isLoading && <ListSkeleton rows={6} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}

      {q.data && (
        <>
          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-tg-text">
              Запланировано ({q.data.pending.length})
            </h2>
            {q.data.pending.length === 0 && (
              <p className="text-xs text-tg-hint">
                Отложенных напоминаний нет: у открытых поручений не проставлен
                срок.
              </p>
            )}
            <div className="divide-y divide-tg-secondary-bg/70 overflow-hidden rounded-xl bg-tg-secondary-bg/40">
              {q.data.pending.map((item) => (
                <div
                  key={`${item.kind}-${item.task_id}-${item.at}`}
                  className="px-3 py-2.5"
                >
                  <div className="text-sm text-tg-text">
                    <span className="font-medium">{item.display_name}</span> ·{" "}
                    {item.kind === "deadline"
                      ? "напоминание о сроке"
                      : "вторая ступень"}
                    {item.moved && (
                      <span className="ml-1 rounded-full bg-tg-link/15 px-1.5 py-0.5 text-[10px] text-tg-link">
                        перенесено вручную
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-[11px] text-tg-hint">
                    {formatMoment(item.at)} · «{item.task_title}»
                  </div>
                  {item.kind === "deadline" && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {moving === item.task_id ? (
                        <>
                          {[
                            { label: "+15 мин", minutes: 15 },
                            { label: "+1 ч", minutes: 60 },
                            { label: "+3 ч", minutes: 180 },
                          ].map((option) => (
                            <button
                              key={option.minutes}
                              type="button"
                              disabled={move.isPending}
                              onClick={() => {
                                haptic("selection");
                                move.mutate({
                                  taskId: item.task_id,
                                  minutes: option.minutes,
                                });
                              }}
                              className="min-h-8 rounded-full bg-tg-link/15 px-2.5 text-[11px] text-tg-link disabled:opacity-50"
                            >
                              {option.label}
                            </button>
                          ))}
                          <button
                            type="button"
                            onClick={() => setMoving(null)}
                            className="min-h-8 rounded-full bg-tg-bg/60 px-2.5 text-[11px] text-tg-hint"
                          >
                            Отмена
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          disabled={move.isPending || skip.isPending}
                          onClick={() => {
                            haptic("selection");
                            setMoving(item.task_id);
                          }}
                          className="min-h-8 rounded-full bg-tg-bg/60 px-2.5 text-[11px] text-tg-text disabled:opacity-50"
                        >
                          Передвинуть
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={skip.isPending}
                        onClick={() => {
                          haptic("medium");
                          void (async () => {
                            const ok = await showConfirm(
                              `Выключить напоминание по «${item.task_title}»?\n\nВернуть можно здесь же, в «Выключено».`,
                            );
                            if (ok) skip.mutate(item.task_id);
                          })();
                        }}
                        className="min-h-8 rounded-full bg-tg-bg/60 px-2.5 text-[11px] text-status-busy disabled:opacity-50"
                      >
                        Выключить
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>

            {(q.data.disabled ?? []).length > 0 && (
              <div className="space-y-2">
                <h2 className="text-sm font-semibold text-tg-text">
                  Выключено ({q.data.disabled.length})
                </h2>
                <div className="divide-y divide-tg-secondary-bg/70 overflow-hidden rounded-xl bg-tg-secondary-bg/40">
                  {q.data.disabled.map((item) => (
                    <div
                      key={`off-${item.task_id}-${item.employee_id}`}
                      className="flex items-start gap-2 px-3 py-2.5"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="text-sm text-tg-text">
                          <span className="font-medium">{item.display_name}</span>{" "}
                          · «{item.task_title}»
                        </div>
                        <div className="mt-0.5 text-[11px] text-tg-hint">
                          Напоминание о сроке не уйдёт. Вторая ступень после
                          просрочки работает отдельно.
                        </div>
                      </div>
                      <button
                        type="button"
                        disabled={restore.isPending}
                        onClick={() => {
                          haptic("selection");
                          restore.mutate(item.task_id);
                        }}
                        className="shrink-0 min-h-8 rounded-full bg-tg-bg/60 px-2.5 text-[11px] text-tg-link disabled:opacity-50"
                      >
                        Вернуть
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-tg-text">
              Отправлено ({q.data.items.length})
            </h2>
            {q.data.items.length === 0 && (
              <p className="text-xs text-tg-hint">Колокольчики пока пустые.</p>
            )}
            <div className="divide-y divide-tg-secondary-bg/70 overflow-hidden rounded-xl bg-tg-secondary-bg/40">
              {q.data.items.map((item) => (
                <div key={item.id} className="flex items-start gap-2 px-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-tg-text break-words">
                      {item.text}
                    </div>
                    <div className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-tg-hint">
                      <span>{item.display_name ?? "без профиля"}</span>
                      <span>· {formatMoment(item.created_at)}</span>
                      {item.department_name && <span>· {item.department_name}</span>}
                      {item.read_at === null && <span>· не прочитано</span>}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={drop.isPending}
                    onClick={() => {
                      haptic("medium");
                      void (async () => {
                        const ok = await showConfirm(
                          "Убрать это уведомление из колокольчика сотрудника?",
                        );
                        if (ok) drop.mutate(item.id);
                      })();
                    }}
                    className="shrink-0 min-h-8 rounded-full bg-tg-bg/60 px-2.5 text-[11px] text-status-busy disabled:opacity-50"
                  >
                    Убрать
                  </button>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </SubScreen>
  );
}

function formatMoment(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
