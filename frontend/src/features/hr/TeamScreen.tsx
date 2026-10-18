import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchDashboard,
  fetchHrSettings,
  muteNotifications,
  updateHrSettings,
  type HrDashboardEmployee,
  type HrDashboardDepartment,
  type HrSettings,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import DepartmentTag from "@/components/DepartmentTag";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";

/**
 * Кабинет управляющего.
 *
 * Порядок блоков = порядок разбора смены: сначала «что требует вмешательства»,
 * потом отделы, потом люди. Расширенные настройки спрятаны в конце, чтобы не
 * мешали оперативной картине.
 */
const STATUS_META: Record<
  HrDashboardEmployee["status"],
  { label: string; icon: string; className: string }
> = {
  done: { label: "смена закрыта", icon: "✅", className: "text-status-free" },
  late: { label: "не закрыта вовремя", icon: "⚠️", className: "text-status-busy" },
  in_progress: { label: "в работе", icon: "⏳", className: "text-tg-text" },
  idle: { label: "не начинал", icon: "—", className: "text-tg-hint" },
};

export default function TeamScreen({
  canManage,
  onBack,
}: {
  canManage: boolean;
  onBack?: () => void;
}) {
  const dashboard = useQuery({
    queryKey: ["hr-dashboard"],
    queryFn: fetchDashboard,
    refetchInterval: 60_000,
  });
  const [showSettings, setShowSettings] = useState(false);

  if (dashboard.isError) {
    return (
      <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        {onBack && (
          <button
            type="button"
            onClick={() => {
              haptic("light");
              onBack();
            }}
            className="min-h-9 min-w-9 rounded-lg text-lg text-tg-link"
            aria-label="Назад"
          >
            ‹
          </button>
        )}
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-tg-text">👀 Команда</div>
          <div className="text-[11px] text-tg-hint">
            {dashboard.data
              ? `${dashboard.data.work_date} · ${
                  dashboard.data.scope === "all" ? "все подразделения" : "моё подразделение"
                }`
              : "Сводка смены"}
          </div>
        </div>
        <button
          type="button"
          onClick={() => void dashboard.refetch()}
          className="min-h-9 rounded-lg px-2 text-xs text-tg-link"
        >
          ⟳
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {dashboard.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {dashboard.data && (
          <>
            <section className="grid grid-cols-2 gap-2">
              <Tile
                label="Смена начата"
                value={`${dashboard.data.shifts_started}/${dashboard.data.total_employees}`}
              />
              <Tile label="Закрыто" value={`${dashboard.data.shifts_done}`} />
              <Tile
                label="Просрочено"
                value={`${dashboard.data.tasks_overdue}`}
                danger={dashboard.data.tasks_overdue > 0}
              />
              <Tile
                label="Проблемы"
                value={`${dashboard.data.open_issues}`}
                danger={dashboard.data.open_issues > 0}
              />
            </section>

            {dashboard.data.attention.length > 0 && (
              <section className="rounded-xl bg-status-busy/10 p-3">
                <h2 className="text-sm font-semibold text-status-busy">
                  Требует внимания
                </h2>
                <ul className="mt-2 space-y-1.5">
                  {dashboard.data.attention.slice(0, 8).map((item, index) => (
                    <li
                      key={`${item.kind}-${item.task_id ?? item.employee_id}-${index}`}
                      className="flex gap-2 text-xs text-tg-text"
                    >
                      <span aria-hidden>
                        {item.kind === "overdue" ? "⏰" : item.kind === "issue" ? "⚠️" : "🌙"}
                      </span>
                      <span className="min-w-0">{item.text}</span>
                    </li>
                  ))}
                </ul>
                {dashboard.data.attention.length > 8 && (
                  <div className="mt-1 text-[11px] text-tg-hint">
                    и ещё {dashboard.data.attention.length - 8}
                  </div>
                )}
              </section>
            )}

            <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
              <h2 className="text-sm font-semibold text-tg-text">Подразделения</h2>
              <div className="mt-2 space-y-2">
                {dashboard.data.departments.length === 0 && (
                  <div className="text-xs text-tg-hint">Подразделений пока нет.</div>
                )}
                {dashboard.data.departments.map((department) => (
                  <DepartmentRow key={department.department_id} row={department} />
                ))}
              </div>
            </section>

            <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-tg-text">Сотрудники</h2>
                <span className="text-[11px] tabular-nums text-tg-hint">
                  {dashboard.data.employees.length}
                </span>
              </div>
              <div className="mt-2 space-y-1.5">
                {dashboard.data.employees.map((employee) => (
                  <EmployeeRow key={employee.employee_id} employee={employee} />
                ))}
              </div>
            </section>

            {dashboard.data.activity.length > 0 && (
              <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
                <h2 className="text-sm font-semibold text-tg-text">Последние действия</h2>
                <ul className="mt-2 space-y-1">
                  {dashboard.data.activity.map((item, index) => (
                    <li
                      key={`${item.at}-${index}`}
                      className="flex items-baseline justify-between gap-2 text-[11px]"
                    >
                      <span className="min-w-0 truncate text-tg-text">
                        {item.display_name ? `${item.display_name}: ` : ""}
                        {item.text}
                      </span>
                      <span className="shrink-0 tabular-nums text-tg-hint">
                        {formatTime(item.at)}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {canManage && (
              <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
                <button
                  type="button"
                  onClick={() => {
                    haptic("selection");
                    setShowSettings((v) => !v);
                  }}
                  aria-expanded={showSettings}
                  className="flex w-full items-center justify-between text-left"
                >
                  <span className="text-sm font-semibold text-tg-text">
                    Рабочие часы и уведомления
                  </span>
                  <span className="text-tg-hint" aria-hidden>
                    {showSettings ? "▾" : "▸"}
                  </span>
                </button>
                {showSettings && <WorkHoursPanel />}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Tile({
  label,
  value,
  danger = false,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div className="rounded-lg bg-tg-secondary-bg/60 p-2">
      <div className={`text-lg font-semibold tabular-nums ${danger ? "text-status-busy" : "text-tg-text"}`}>
        {value}
      </div>
      <div className="text-[11px] text-tg-hint">{label}</div>
    </div>
  );
}

function DepartmentRow({ row }: { row: HrDashboardDepartment }) {
  const percent = row.employees ? Math.round((100 * row.done) / row.employees) : 0;
  return (
    <div className="rounded-lg bg-tg-bg/50 p-2">
      <div className="flex items-center gap-2">
        <span aria-hidden>{row.emoji ?? "•"}</span>
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-tg-text">
          {row.name}
        </span>
        <span className="text-[11px] tabular-nums text-tg-hint">
          {row.started}/{row.employees}
        </span>
      </div>
      <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-tg-secondary-bg">
        <div
          className="h-full rounded-full bg-tg-link"
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-tg-hint">
        <span>закрыто {row.done}</span>
        {row.overdue_tasks > 0 && (
          <span className="text-status-busy">просрочено {row.overdue_tasks}</span>
        )}
        {row.open_issues > 0 && (
          <span className="text-status-busy">проблем {row.open_issues}</span>
        )}
      </div>
    </div>
  );
}

function EmployeeRow({ employee }: { employee: HrDashboardEmployee }) {
  const meta = STATUS_META[employee.status];
  const progress =
    employee.checklist_total > 0
      ? Math.round((100 * employee.checklist_done) / employee.checklist_total)
      : 0;
  return (
    <div className="rounded-lg bg-tg-bg/50 p-2">
      <div className="flex min-w-0 items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-xs text-tg-text">
          {employee.display_name}
        </span>
        <DepartmentTag
          name={employee.department_name}
          emoji={employee.department_emoji}
        />
        <span className={`shrink-0 text-[10px] ${meta.className}`}>
          <span aria-hidden>{meta.icon}</span> {meta.label}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-tg-secondary-bg">
          <div
            className={`h-full rounded-full ${employee.status === "late" ? "bg-status-busy" : "bg-tg-link"}`}
            style={{ width: `${progress}%` }}
          />
        </div>
        <span className="shrink-0 text-[10px] tabular-nums text-tg-hint">
          {employee.checklist_done}/{employee.checklist_total}
        </span>
        {employee.tasks_overdue > 0 && (
          <span className="shrink-0 text-[10px] text-status-busy">
            ⏰ {employee.tasks_overdue}
          </span>
        )}
      </div>
    </div>
  );
}

function WorkHoursPanel() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["hr-settings"], queryFn: fetchHrSettings });
  const [open, setOpen] = useState<string | null>(null);
  const [close, setClose] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (body: Partial<HrSettings>) => updateHrSettings(body),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-settings"], data);
      void qc.invalidateQueries({ queryKey: ["hr-dashboard"] });
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const mute = useMutation({
    mutationFn: (hours: number) => muteNotifications(hours),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-settings"], data);
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  if (settings.isLoading || !settings.data) {
    return <div className="mt-2 text-[11px] text-tg-hint">Загружаем…</div>;
  }

  const data = settings.data;
  const openValue = open ?? data.work_open;
  const closeValue = close ?? data.work_close;

  return (
    <div className="mt-2 space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="rounded-lg bg-tg-bg/50 p-2 text-[11px] text-tg-hint">
          Открытие
          <input
            type="time"
            value={openValue}
            onChange={(event) => setOpen(event.target.value)}
            className="mt-1 w-full bg-transparent text-sm text-tg-text outline-none"
          />
        </label>
        <label className="rounded-lg bg-tg-bg/50 p-2 text-[11px] text-tg-hint">
          Закрытие
          <input
            type="time"
            value={closeValue}
            onChange={(event) => setClose(event.target.value)}
            className="mt-1 w-full bg-transparent text-sm text-tg-text outline-none"
          />
        </label>
      </div>
      <button
        type="button"
        disabled={save.isPending}
        onClick={() => save.mutate({ work_open: openValue, work_close: closeValue })}
        className="min-h-10 w-full rounded-lg bg-tg-button text-xs font-medium text-tg-button-text disabled:opacity-50"
      >
        Сохранить часы
      </button>

      <label className="flex items-center justify-between rounded-lg bg-tg-bg/50 p-2 text-[11px] text-tg-text">
        <span>Алерты только в рабочее время</span>
        <input
          type="checkbox"
          checked={data.notify_only_work_hours}
          onChange={(event) =>
            save.mutate({ notify_only_work_hours: event.target.checked })
          }
          className="h-4 w-4"
        />
      </label>

      <div className="rounded-lg bg-tg-bg/50 p-2">
        <label className="flex items-center justify-between text-[11px] text-tg-text">
          <span>Вторая ступень: пинг админам</span>
          <input
            type="checkbox"
            checked={data.escalation_second_enabled}
            onChange={(event) =>
              save.mutate({ escalation_second_enabled: event.target.checked })
            }
            className="h-4 w-4"
          />
        </label>
        <label className="mt-1.5 flex items-center justify-between gap-2 text-[11px] text-tg-hint">
          <span>Если руководитель молчит</span>
          <select
            value={data.escalation_second_hours}
            disabled={!data.escalation_second_enabled || save.isPending}
            onChange={(event) =>
              save.mutate({ escalation_second_hours: Number(event.target.value) })
            }
            className="min-h-9 rounded-lg border border-tg-secondary-bg bg-tg-bg px-2 text-xs text-tg-text disabled:opacity-50"
            aria-label="Порог второй ступени, часы"
          >
            {[...new Set([1, 2, 4, 8, 12, 24, 48, data.escalation_second_hours])]
              .sort((a, b) => a - b)
              .map((hours) => (
              <option key={hours} value={hours}>
                {hours} ч
              </option>
              ))}
          </select>
        </label>
      </div>

      <div className="rounded-lg bg-tg-bg/50 p-2">
        <div className="text-[11px] text-tg-hint">
          {data.muted_until
            ? `Мьют до ${formatDateTime(data.muted_until)}`
            : "Мьют выключен"}
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {[
            { label: "24ч", hours: 24 },
            { label: "3 дня", hours: 72 },
            { label: "7 дней", hours: 168 },
            { label: "30 дней", hours: 720 },
          ].map((option) => (
            <button
              key={option.hours}
              type="button"
              disabled={mute.isPending}
              onClick={() => mute.mutate(option.hours)}
              className="min-h-8 rounded-full bg-tg-secondary-bg px-2.5 text-[11px] text-tg-text disabled:opacity-50"
            >
              {option.label}
            </button>
          ))}
          {data.muted_until && (
            <button
              type="button"
              disabled={mute.isPending}
              onClick={() => mute.mutate(0)}
              className="min-h-8 rounded-full bg-status-busy/15 px-2.5 text-[11px] text-status-busy disabled:opacity-50"
            >
              Снять
            </button>
          )}
        </div>
      </div>
      <p className="text-[10px] text-tg-hint">
        Ночью уведомления не уходят в чат, но копятся в приложении — утренний
        разбор не потеряется.
      </p>
    </div>
  );
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
