import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { humanizeApiError } from "@/api/client";
import {
  clearTrainingDay,
  fetchTrainingPlan,
  patchTrainingPlan,
  setTrainingDay,
  type HrEmployeePlan,
  type HrRateType,
} from "@/api/hrTrainingPlan";
import { ListSkeleton } from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import { haptic, showAlert } from "@/tg/webapp";
import SubScreen from "./SubScreen";

/**
 * Расписание обучения: какие смены у новичка ещё учебные, а какие обычные.
 *
 * Раньше это был один флаг «учимся вместе» на весь профиль. Теперь управляющий
 * раскладывает первые смены по дням: правило «первые N смен» + точечные
 * исключения. Рядом — ставка (полная/частичная), чтобы не держать её в голове.
 *
 * План ничего не блокирует: чек-листы, поручения и уведомления работают
 * одинаково в учебный и обычный день — меняется только сопровождение.
 */
export default function TrainingPlanScreen({ onBack }: { onBack: () => void }) {
  const qc = useQueryClient();
  const [openId, setOpenId] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["admin", "training-plan"],
    queryFn: () => fetchTrainingPlan(14),
    staleTime: 20_000,
  });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["admin", "training-plan"] });
    void qc.invalidateQueries({ queryKey: ["hr-training"] });
    void qc.invalidateQueries({ queryKey: ["hr-employee"] });
  };

  const onError = (error: unknown) => void showAlert(humanizeApiError(error));

  const patch = useMutation({
    mutationFn: (input: {
      id: number;
      body: { rate_type?: HrRateType; training_days?: number };
    }) => patchTrainingPlan(input.id, input.body),
    onSuccess: () => {
      haptic("success");
      refresh();
    },
    onError,
  });

  const toggleDay = useMutation({
    mutationFn: (input: { id: number; day: string; isTraining: boolean }) =>
      setTrainingDay(input.id, input.day, input.isTraining),
    onSuccess: () => {
      haptic("selection");
      refresh();
    },
    onError,
  });

  const resetDay = useMutation({
    mutationFn: (input: { id: number; day: string }) =>
      clearTrainingDay(input.id, input.day),
    onSuccess: () => {
      haptic("success");
      refresh();
    },
    onError,
  });

  const labels = q.data?.rate_labels ?? {
    full: "Полная ставка",
    partial: "Частичная ставка",
  };

  return (
    <SubScreen
      title="🎓 Обучение и ставка"
      subtitle="Учебные и обычные смены, ставка сотрудника"
      onBack={onBack}
    >
      <p className="text-[11px] text-tg-hint">
        Учебные смены считаются по табелю: первые N отработанных смен. Больничный
        или пропуск учебную не съедает, перенесённая смена остаётся в счёте. Пока
        табель пуст, работает старый расчёт по дате найма. Любой день можно
        переключить вручную.
      </p>

      {q.isLoading && <ListSkeleton rows={5} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}

      {q.data && q.data.items.length === 0 && (
        <p className="text-xs text-tg-hint">Сотрудников в твоём подразделении нет.</p>
      )}

      {q.data && (
        <div className="space-y-2">
          {q.data.items.map((plan) => (
            <PlanCard
              key={plan.employee_id}
              plan={plan}
              labels={labels}
              open={openId === plan.employee_id}
              onToggleOpen={() => {
                haptic("light");
                setOpenId(openId === plan.employee_id ? null : plan.employee_id);
              }}
              busy={patch.isPending || toggleDay.isPending || resetDay.isPending}
              onRate={(rate) =>
                patch.mutate({
                  id: plan.employee_id,
                  body: { rate_type: rate },
                })
              }
              onTrainingDays={(value) =>
                patch.mutate({
                  id: plan.employee_id,
                  body: { training_days: value },
                })
              }
              onToggleDay={(day, isTraining) =>
                toggleDay.mutate({
                  id: plan.employee_id,
                  day,
                  isTraining,
                })
              }
              onResetDay={(day) =>
                resetDay.mutate({ id: plan.employee_id, day })
              }
            />
          ))}
        </div>
      )}
    </SubScreen>
  );
}

function PlanCard({
  plan,
  labels,
  open,
  onToggleOpen,
  busy,
  onRate,
  onTrainingDays,
  onToggleDay,
  onResetDay,
}: {
  plan: HrEmployeePlan;
  labels: Record<string, string>;
  open: boolean;
  onToggleOpen: () => void;
  busy: boolean;
  onRate: (rate: HrRateType) => void;
  onTrainingDays: (value: number) => void;
  onToggleDay: (day: string, isTraining: boolean) => void;
  onResetDay: (day: string) => void;
}) {
  const trainingCount = plan.days.filter((item) => item.is_training).length;
  const explicit = plan.days.filter((item) => item.explicit);
  const newcomer =
    plan.onboarding_state !== "done" || plan.hire_date === null;

  return (
    <section className="overflow-hidden rounded-xl bg-tg-secondary-bg/50">
      <button
        type="button"
        onClick={onToggleOpen}
        className="flex w-full items-start gap-2 px-3 py-2.5 text-left active:scale-[0.99]"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-sm font-medium text-tg-text">
              {plan.display_name}
            </span>
            {newcomer && (
              <span className="rounded-full bg-tg-link/15 px-1.5 py-0.5 text-[10px] text-tg-link">
                новичок
              </span>
            )}
          </div>
          <div className="mt-0.5 truncate text-[11px] text-tg-hint">
            {[plan.position, plan.department_name].filter(Boolean).join(" · ") ||
              "Без должности"}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-tg-hint">
            <span className="text-tg-text">{labels[plan.rate_type] ?? plan.rate_type}</span>
            <span>
              · учебных {trainingCount} из {plan.days.length}
            </span>
            {explicit.length > 0 && <span>· {explicit.length} вручную</span>}
            {!plan.has_shifts && <span>· табель пуст</span>}
          </div>
        </div>
        <span className="shrink-0 pt-0.5 text-xs text-tg-hint">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-tg-bg/50 px-3 py-3">
          <div>
            <div className="text-[11px] font-medium text-tg-hint">Ставка</div>
            <div className="mt-1 flex gap-1.5">
              {(["full", "partial"] as HrRateType[]).map((rate) => (
                <button
                  key={rate}
                  type="button"
                  disabled={busy}
                  onClick={() => onRate(rate)}
                  className={`min-h-9 flex-1 rounded-lg px-2 text-xs transition-colors disabled:opacity-50 ${
                    plan.rate_type === rate
                      ? "bg-tg-button text-tg-button-text"
                      : "bg-tg-bg/60 text-tg-text"
                  }`}
                >
                  {labels[rate] ?? rate}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="text-[11px] font-medium text-tg-hint">
              Учебных смен по табелю
            </div>
            <div className="mt-1 flex items-center gap-2">
              <button
                type="button"
                disabled={busy || plan.training_days <= 0}
                onClick={() => onTrainingDays(Math.max(0, plan.training_days - 1))}
                className="min-h-9 min-w-9 rounded-lg bg-tg-bg/60 text-sm text-tg-text disabled:opacity-40"
                aria-label="Меньше учебных смен"
              >
                −
              </button>
              <span className="min-w-8 text-center text-sm tabular-nums text-tg-text">
                {plan.training_days}
              </span>
              <button
                type="button"
                disabled={busy || plan.training_days >= 30}
                onClick={() => onTrainingDays(Math.min(30, plan.training_days + 1))}
                className="min-h-9 min-w-9 rounded-lg bg-tg-bg/60 text-sm text-tg-text disabled:opacity-40"
                aria-label="Больше учебных смен"
              >
                +
              </button>
              <span className="text-[10px] text-tg-hint">
                {plan.has_shifts
                  ? "считаем отработанные смены"
                  : plan.hire_date
                    ? `табель пуст · с ${formatDate(plan.hire_date)}`
                    : "табель пуст · включено «учимся вместе»"}
              </span>
            </div>
          </div>

          <div>
            <div className="text-[11px] font-medium text-tg-hint">
              Ближайшие две недели
            </div>
            <div className="mt-1 grid grid-cols-7 gap-1">
              {plan.days.map((item) => (
                <button
                  key={item.day}
                  type="button"
                  disabled={busy}
                  onClick={() => onToggleDay(item.day, !item.is_training)}
                  title={
                    item.is_training
                      ? "Учебная смена — нажми, чтобы сделать обычной"
                      : "Обычная смена — нажми, чтобы сделать учебной"
                  }
                  className={`relative min-h-11 rounded-lg px-1 py-1 text-center text-[10px] leading-tight transition-colors disabled:opacity-50 ${
                    item.is_training
                      ? "bg-tg-link/20 text-tg-link"
                      : "bg-tg-bg/50 text-tg-hint"
                  }`}
                >
                  <div className="uppercase">{weekday(item.day)}</div>
                  <div className="text-sm tabular-nums">{dayNumber(item.day)}</div>
                  {item.shift_status && (
                    <div className="text-[9px] opacity-70">
                      {SHIFT_CHAR[item.shift_status] ?? "·"}
                    </div>
                  )}
                  {item.explicit && (
                    <span
                      className="absolute right-1 top-0.5 text-[9px]"
                      aria-hidden
                    >
                      •
                    </span>
                  )}
                </button>
              ))}
            </div>
            <div className="mt-1 text-[10px] text-tg-hint">
              Синее — учебная смена, серое — обычная. Точка — день задан вручную,
              буква — статус в табеле (Р работа, П план, Б больничный, Н не пришёл,
              В выходной, О отпуск).
            </div>
          </div>

          {explicit.length > 0 && (
            <div className="space-y-1">
              {explicit.map((item) => (
                <div
                  key={`rule-${item.day}`}
                  className="flex items-center gap-2 text-[11px]"
                >
                  <span className="min-w-0 flex-1 text-tg-text">
                    {formatDate(item.day)} —{" "}
                    {item.is_training ? "учебная" : "обычная"} (вручную)
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onResetDay(item.day)}
                    className="min-h-8 shrink-0 rounded-full bg-tg-bg/60 px-2.5 text-[11px] text-tg-link disabled:opacity-50"
                  >
                    Вернуть правило
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

const SHIFT_CHAR: Record<string, string> = {
  planned: "П",
  worked: "Р",
  sick: "Б",
  absent: "Н",
  dayoff: "В",
  vacation: "О",
};

function parseDay(day: string): Date {
  return new Date(`${day}T00:00:00`);
}

function formatDate(day: string): string {
  const date = parseDay(day);
  if (Number.isNaN(date.getTime())) return day;
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

function weekday(day: string): string {
  const date = parseDay(day);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("ru-RU", { weekday: "short" }).slice(0, 2);
}

function dayNumber(day: string): string {
  const date = parseDay(day);
  if (Number.isNaN(date.getTime())) return "";
  return String(date.getDate());
}
