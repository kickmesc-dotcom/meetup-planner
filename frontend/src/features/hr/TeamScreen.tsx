import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  executeReset,
  fetchDashboard,
  fetchHrSettings,
  fetchResetPreview,
  muteNotifications,
  updateHrSettings,
  type HrDashboardEmployee,
  type HrDashboardDepartment,
  type HrSettings,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import DepartmentTag from "@/components/DepartmentTag";
import Icon, { type IconName } from "@/components/Icon";
import ChevronToggle from "@/components/ChevronToggle";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton, SkeletonText } from "@/components/Skeleton";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import EmployeeCardSheet from "@/features/hr/EmployeeCardSheet";
import InvitationsScreen from "@/features/admin/InvitationsScreen";
import { useTx, type Locale } from "@/i18n";

/**
 * Кабинет управляющего.
 *
 * Порядок блоков = порядок разбора смены: сначала «что требует вмешательства»,
 * потом отделы, потом люди. Расширенные настройки спрятаны в конце, чтобы не
 * мешали оперативной картине.
 */
// P1.4: статусы — SVG, а не эмодзи. На Windows «⏳» и «✅» рисовались
// цветными картинками разного размера и ломали строку статуса.
const STATUS_META: Record<
  HrDashboardEmployee["status"],
  { label: string; icon: IconName | null; className: string }
> = {
  done: { label: "смена закрыта", icon: "check", className: "text-status-free" },
  late: { label: "не закрыта вовремя", icon: "alert", className: "text-status-busy" },
  in_progress: { label: "в работе", icon: "clock", className: "text-tg-text" },
  idle: { label: "не начинал", icon: null, className: "text-tg-hint" },
};

export default function TeamScreen({
  canManage,
  onBack,
}: {
  canManage: boolean;
  onBack?: () => void;
}) {
  const { tx, locale } = useTx();
  const dashboard = useQuery({
    queryKey: ["hr-dashboard"],
    queryFn: fetchDashboard,
    refetchInterval: 60_000,
  });
  const [showSettings, setShowSettings] = useState(false);
  // Поиск по фамилии, должности или отделу: в смену важно быстро найти
  // конкретного человека, а не листать весь штат.
  const [search, setSearch] = useState("");
  // Карточка человека: тап по имени в сводке (активность — по видимости
  // профиля, решает сервер).
  const [cardEmployeeId, setCardEmployeeId] = useState<number | null>(null);
  // Приглашения — здесь, а не только в админке: руководитель ищет людей в
  // «Команде», а кабинет платформы клиенту недоступен (и не должен быть).
  const [showInvites, setShowInvites] = useState(false);

  if (showInvites) {
    return <InvitationsScreen onBack={() => setShowInvites(false)} />;
  }

  if (dashboard.isError) {
    return (
      <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />
    );
  }

  const needle = search.trim().toLowerCase();
  const employees = (dashboard.data?.employees ?? []).filter(
    (employee) =>
      needle === "" ||
      employee.display_name.toLowerCase().includes(needle) ||
      (employee.position ?? "").toLowerCase().includes(needle) ||
      (employee.badge ?? "").toLowerCase().includes(needle) ||
      (employee.department_name ?? "").toLowerCase().includes(needle),
  );

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
            className="min-h-11 min-w-11 rounded-tile text-lg text-tg-link"
            aria-label={tx("Назад")}
          >
            ‹
          </button>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-sm font-semibold text-tg-text">
            <Icon name="team" size={16} />
            {tx("Команда")}
          </div>
          <div className="text-xs text-tg-hint">
            {dashboard.data
              ? `${dashboard.data.work_date} · ${
                  dashboard.data.scope === "all"
                    ? tx("все подразделения")
                    : tx("моё подразделение")
                }`
              : tx("Сводка смены")}
          </div>
        </div>
        <button
          type="button"
          onClick={() => void dashboard.refetch()}
          className="min-h-11 min-w-11 rounded-tile px-2 text-xs text-tg-link"
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
                label={tx("Смена начата")}
                value={`${dashboard.data.shifts_started}/${dashboard.data.total_employees}`}
              />
              <Tile label={tx("Закрыто")} value={`${dashboard.data.shifts_done}`} />
              <Tile
                label={tx("Просрочено")}
                value={`${dashboard.data.tasks_overdue}`}
                danger={dashboard.data.tasks_overdue > 0}
              />
              <Tile
                label={tx("Проблемы")}
                value={`${dashboard.data.open_issues}`}
                danger={dashboard.data.open_issues > 0}
              />
            </section>

            {dashboard.data.attention.length > 0 && (
              <section className="rounded-card bg-status-busy/10 p-3">
                <h2 className="text-sm font-semibold text-status-busy">
                  {tx("Требует внимания")}
                </h2>
                <ul className="mt-2 space-y-1.5">
                  {dashboard.data.attention.slice(0, 8).map((item, index) => (
                    <li
                      key={`${item.kind}-${item.task_id ?? item.employee_id}-${index}`}
                      className="flex gap-2 text-xs text-tg-text"
                    >
                      <span className="mt-0.5 shrink-0 text-tg-hint" aria-hidden>
                        <Icon
                          name={
                            item.kind === "overdue"
                              ? "clock"
                              : item.kind === "issue"
                                ? "alert"
                                : "send"
                          }
                          size={14}
                        />
                      </span>
                      <span className="min-w-0">{item.text}</span>
                    </li>
                  ))}
                </ul>
                {dashboard.data.attention.length > 8 && (
                  <div className="mt-1 text-xs text-tg-hint">
                    {tx("и ещё {count}", {
                      count: dashboard.data.attention.length - 8,
                    })}
                  </div>
                )}
              </section>
            )}

            <section className="rounded-card bg-tg-secondary-bg/60 p-3">
              <h2 className="text-sm font-semibold text-tg-text">
                {tx("Позвать в команду")}
              </h2>
              <p className="mt-1 text-xs text-tg-hint">
                {tx(
                  "Ссылка-приглашение или код компании: человек входит сам и сразу попадает в свой отдел.",
                )}
              </p>
              <button
                type="button"
                onClick={() => {
                  haptic("selection");
                  setShowInvites(true);
                }}
                className="mt-2 min-h-11 w-full rounded-tile bg-tg-button text-xs font-medium text-tg-button-text"
              >
                {tx("Пригласить сотрудника")}
              </button>
            </section>

            <section className="rounded-card bg-tg-secondary-bg/60 p-3">
              <h2 className="text-sm font-semibold text-tg-text">
                {tx("Подразделения")}
              </h2>
              <div className="mt-2 space-y-2">
                {dashboard.data.departments.length === 0 && (
                  <div className="text-xs text-tg-hint">
                    {tx("Подразделений пока нет.")}
                  </div>
                )}
                {dashboard.data.departments.map((department) => (
                  <DepartmentRow key={department.department_id} row={department} />
                ))}
              </div>
            </section>

            <section className="rounded-card bg-tg-secondary-bg/60 p-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-tg-text">
                  {tx("Сотрудники")}
                </h2>
                <span className="text-xs tabular-nums text-tg-hint">
                  {employees.length}
                  {needle
                    ? ` ${tx("из {count}", {
                        count: dashboard.data.employees.length,
                      })}`
                    : ""}
                </span>
              </div>
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={tx("Найти человека или должность")}
                aria-label={tx("Поиск по сотрудникам")}
                className="mt-2 min-h-9 w-full rounded-tile bg-tg-bg/50 px-2 text-xs text-tg-text placeholder:text-tg-hint"
              />
              <div className="mt-2 space-y-1.5">
                {employees.length === 0 && (
                  <div className="text-xs text-tg-hint">
                    {needle
                      ? tx("Никого не нашли.")
                      : tx("Сотрудников пока нет.")}
                  </div>
                )}
                {employees.map((employee) => (
                  <EmployeeRow
                    key={employee.employee_id}
                    employee={employee}
                    onOpen={() => setCardEmployeeId(employee.employee_id)}
                  />
                ))}
              </div>
            </section>

            {dashboard.data.activity.length > 0 && (
              <section className="rounded-card bg-tg-secondary-bg/60 p-3">
                <h2 className="text-sm font-semibold text-tg-text">
                  {tx("Последние действия")}
                </h2>
                <ul className="mt-2 space-y-1">
                  {dashboard.data.activity.map((item, index) => (
                    <li
                      key={`${item.at}-${index}`}
                      className="flex items-baseline justify-between gap-2 text-xs"
                    >
                      <span className="min-w-0 truncate text-tg-text">
                        {item.display_name ? `${item.display_name}: ` : ""}
                        {item.text}
                      </span>
                      <span className="shrink-0 tabular-nums text-tg-hint">
                        {formatTime(item.at, locale)}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {canManage && (
              <section className="rounded-card bg-tg-secondary-bg/60 p-3">
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
                    {tx("Рабочие часы и уведомления")}
                  </span>
                  <span className="text-tg-hint" aria-hidden>
                    <ChevronToggle open={showSettings} />
                  </span>
                </button>
                {showSettings && (
                  <>
                    <WorkHoursPanel />
                    <DangerZone />
                  </>
                )}
              </section>
            )}
          </>
        )}
      </div>

      {cardEmployeeId !== null && (
        <EmployeeCardSheet
          employeeId={cardEmployeeId}
          onClose={() => setCardEmployeeId(null)}
        />
      )}
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
    <div className="rounded-tile bg-tg-secondary-bg/60 p-2">
      <div className={`text-lg font-semibold tabular-nums ${danger ? "text-status-busy" : "text-tg-text"}`}>
        {value}
      </div>
      <div className="text-xs text-tg-hint">{label}</div>
    </div>
  );
}

function DepartmentRow({ row }: { row: HrDashboardDepartment }) {
  const { tx } = useTx();
  const percent = row.employees ? Math.round((100 * row.done) / row.employees) : 0;
  return (
    <div className="rounded-tile bg-tg-bg/50 p-2">
      <div className="flex items-center gap-2">
        <span aria-hidden>{row.emoji ?? "•"}</span>
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-tg-text">
          {row.name}
        </span>
        <span className="text-xs tabular-nums text-tg-hint">
          {row.started}/{row.employees}
        </span>
      </div>
      <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-tg-secondary-bg">
        <div
          className="h-full rounded-full bg-tg-link"
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-2xs text-tg-hint">
        <span>{tx("закрыто {count}", { count: row.done })}</span>
        {row.overdue_tasks > 0 && (
          <span className="text-status-busy">
            {tx("просрочено {count}", { count: row.overdue_tasks })}
          </span>
        )}
        {row.open_issues > 0 && (
          <span className="text-status-busy">
            {tx("проблем {count}", { count: row.open_issues })}
          </span>
        )}
      </div>
    </div>
  );
}

function EmployeeRow({
  employee,
  onOpen,
}: {
  employee: HrDashboardEmployee;
  /** Тап по человеку открывает его карточку (активность — по видимости). */
  onOpen: () => void;
}) {
  const { tx } = useTx();
  const meta = STATUS_META[employee.status];
  const progress =
    employee.checklist_total > 0
      ? Math.round((100 * employee.checklist_done) / employee.checklist_total)
      : 0;
  return (
    <div className="rounded-tile bg-tg-bg/50 p-2">
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onOpen();
          }}
          className="min-w-0 flex-1 truncate text-left text-xs text-tg-text"
          title={tx("Открыть карточку")}
        >
          {employee.display_name}
          {(employee.position ?? employee.badge) && (
            <span className="text-tg-hint">
              {" "}· {employee.position ?? employee.badge}
            </span>
          )}
        </button>
        <DepartmentTag
          name={employee.department_name}
          emoji={employee.department_emoji}
        />
        <span className={`inline-flex shrink-0 items-center gap-1 text-2xs ${meta.className}`}>
          {meta.icon && <Icon name={meta.icon} size={12} />}
          {tx(meta.label)}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-tg-secondary-bg">
          <div
            className={`h-full rounded-full ${employee.status === "late" ? "bg-status-busy" : "bg-tg-link"}`}
            style={{ width: `${progress}%` }}
          />
        </div>
        <span className="shrink-0 text-2xs tabular-nums text-tg-hint">
          {employee.checklist_done}/{employee.checklist_total}
        </span>
        {employee.tasks_overdue > 0 && (
          <span className="inline-flex shrink-0 items-center gap-1 text-2xs text-status-busy">
            <Icon name="clock" size={12} />
            {employee.tasks_overdue}
          </span>
        )}
      </div>
    </div>
  );
}

function WorkHoursPanel() {
  const { tx, locale } = useTx();
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
    // Настройки отдела — две строки полей; держим их форму, а не надпись.
    return <SkeletonText lines={2} className="mt-2" />;
  }

  const data = settings.data;
  const openValue = open ?? data.work_open;
  const closeValue = close ?? data.work_close;

  return (
    <div className="mt-2 space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="rounded-tile bg-tg-bg/50 p-2 text-xs text-tg-hint">
          {tx("Открытие")}
          <input
            type="time"
            value={openValue}
            onChange={(event) => setOpen(event.target.value)}
            className="mt-1 w-full bg-transparent text-sm text-tg-text outline-none"
          />
        </label>
        <label className="rounded-tile bg-tg-bg/50 p-2 text-xs text-tg-hint">
          {tx("Закрытие")}
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
        className="min-h-10 w-full rounded-tile bg-tg-button text-xs font-medium text-tg-button-text disabled:opacity-50"
      >
        {tx("Сохранить часы")}
      </button>

      <label className="flex items-center justify-between rounded-tile bg-tg-bg/50 p-2 text-xs text-tg-text">
        <span>{tx("Алерты только в рабочее время")}</span>
        <input
          type="checkbox"
          checked={data.notify_only_work_hours}
          onChange={(event) =>
            save.mutate({ notify_only_work_hours: event.target.checked })
          }
          className="h-4 w-4"
        />
      </label>

      <div className="rounded-tile bg-tg-bg/50 p-2">
        <label className="flex items-center justify-between text-xs text-tg-text">
          <span>{tx("Вторая ступень: пинг админам")}</span>
          <input
            type="checkbox"
            checked={data.escalation_second_enabled}
            onChange={(event) =>
              save.mutate({ escalation_second_enabled: event.target.checked })
            }
            className="h-4 w-4"
          />
        </label>
        <label className="mt-1.5 flex items-center justify-between gap-2 text-xs text-tg-hint">
          <span>{tx("Если руководитель молчит")}</span>
          <select
            value={data.escalation_second_hours}
            disabled={!data.escalation_second_enabled || save.isPending}
            onChange={(event) =>
              save.mutate({ escalation_second_hours: Number(event.target.value) })
            }
            className="min-h-9 rounded-tile border border-tg-secondary-bg bg-tg-bg px-2 text-xs text-tg-text disabled:opacity-50"
            aria-label={tx("Порог второй ступени, часы")}
          >
            {[...new Set([1, 2, 4, 8, 12, 24, 48, data.escalation_second_hours])]
              .sort((a, b) => a - b)
              .map((hours) => (
              <option key={hours} value={hours}>
                {tx("{hours} ч", { hours })}
              </option>
              ))}
          </select>
        </label>
        <label className="mt-1.5 flex items-center justify-between gap-2 text-xs text-tg-text">
          <span>{tx("Напоминать в каждой смене")}</span>
          <input
            type="checkbox"
            checked={data.escalation_second_repeat}
            disabled={!data.escalation_second_enabled || save.isPending}
            onChange={(event) =>
              save.mutate({ escalation_second_repeat: event.target.checked })
            }
            className="h-4 w-4"
          />
        </label>
      </div>

      <div className="rounded-tile bg-tg-bg/50 p-2">
        <div className="text-xs text-tg-hint">
          {data.muted_until
            ? tx("Мьют до {when}", {
                when: formatDateTime(data.muted_until, locale),
              })
            : tx("Мьют выключен")}
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
              className="min-h-8 rounded-full bg-tg-secondary-bg px-2.5 text-xs text-tg-text disabled:opacity-50"
            >
              {tx(option.label)}
            </button>
          ))}
          {data.muted_until && (
            <button
              type="button"
              disabled={mute.isPending}
              onClick={() => mute.mutate(0)}
              className="min-h-8 rounded-full bg-status-busy/15 px-2.5 text-xs text-status-busy disabled:opacity-50"
            >
              {tx("Снять")}
            </button>
          )}
        </div>
      </div>
      <p className="text-2xs text-tg-hint">
        {tx(
          "Ночью уведомления не уходят в чат, но копятся в приложении — утренний разбор не потеряется.",
        )}
      </p>
    </div>
  );
}

function DangerZone() {
  const { tx } = useTx();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  /**
   * Два подтверждения подряд: первое — цифры, второе — необратимость.
   * Токен привязан к цифрам, поэтому если между шагами что-то изменилось,
   * сервер откажет, а не удалит больше показанного.
   */
  const run = async () => {
    haptic("medium");
    setBusy(true);
    try {
      const preview = await fetchResetPreview();
      const counts = preview.counts;
      if (!counts.tasks && !counts.issues) {
        // Объясняем, почему нечего: обычно открытое висит в тестовом пуле,
        // а его эта кнопка не трогает (см. `hr_reset`).
        await showAlert(
          [tx("Сбрасывать нечего — всё уже закрыто."), ...preview.notes].join(
            "\n\n",
          ),
        );
        return;
      }
      const first = await showConfirm(
        `${tx("Удалить {tasks} поручений и {issues} проблем?", {
          tasks: counts.tasks,
          issues: counts.issues,
        })}\n\n${preview.scope}.`,
      );
      if (!first) return;
      const second = await showConfirm(
        tx(
          "Точно? Действие необратимо. Завершённые поручения и история останутся.",
        ),
      );
      if (!second) return;
      const done = await executeReset(preview.token, "СБРОС");
      haptic("success");
      await qc.invalidateQueries();
      await showAlert(
        tx("Удалено: поручений {tasks}, проблем {issues}.", {
          tasks: done.tasks ?? 0,
          issues: done.issues ?? 0,
        }),
      );
    } catch (error) {
      const text = String(error);
      await showAlert(
        text.includes("reset_preview_stale")
          ? tx("Данные изменились, пока ты подтверждал. Открой сброс заново.")
          : humanizeApiError(error),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 rounded-tile border border-status-busy/30 bg-status-busy/5 p-2">
      <div className="text-xs font-medium text-status-busy">
        {tx("Опасная зона")}
      </div>
      <p className="mt-0.5 text-2xs text-tg-hint">
        {tx(
          "Убирает незакрытые поручения и открытые проблемы. Завершённые задачи, KPI и история сдач остаются; тестовый пул сбрасывается отдельно.",
        )}
      </p>
      <button
        type="button"
        disabled={busy}
        onClick={() => void run()}
        className="mt-2 min-h-9 w-full rounded-tile bg-status-busy/15 text-xs font-medium text-status-busy disabled:opacity-50"
      >
        {busy ? (
          tx("Считаем…")
        ) : (
          <span className="inline-flex items-center gap-1.5">
            <Icon name="trash" size={14} />
            {tx("Сбросить текущую работу")}
          </span>
        )}
      </button>
    </div>
  );
}

function formatTime(iso: string, locale: Locale): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(locale === "en" ? "en-GB" : "ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDateTime(iso: string, locale: Locale): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(locale === "en" ? "en-GB" : "ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
