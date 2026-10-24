import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createAdminTask,
  fetchAdminEmployees,
  fetchAdminTasks,
  fetchDepartments,
  setAdminTaskStatus,
  type HrAdminTask,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import { InlineIcon } from "@/components/Icon";
import SubScreen from "./SubScreen";

import { useTx } from "@/i18n";
/**
 * Поручения: создание и список — в приложении, без чата с ботом.
 *
 * Главное здесь — срок. Раньше он задавался минутами («через 30 минут», «до
 * 18:00») и не годился для точных сценариев: «в 17:30:00 смена закончилась».
 * Теперь дата, время и секунды вводятся явно; рядом быстрые кнопки, чтобы
 * обычный случай оставался одним тапом.
 *
 * Секунды важны ещё и потому, что сервер хранит `timestamptz` и сравнивает
 * срок с точностью до микросекунд: два поручения с разницей в 5 секунд — это
 * разные приоритеты у планировщика напоминаний, а не «одно и то же».
 */
export default function AdminTasksScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const tasksQ = useQuery({
    queryKey: ["hr-admin-tasks"],
    queryFn: () => fetchAdminTasks(),
  });
  const employeesQ = useQuery({
    queryKey: ["hr-admin-employees"],
    queryFn: fetchAdminEmployees,
  });
  const departmentsQ = useQuery({
    queryKey: ["hr-departments"],
    queryFn: fetchDepartments,
  });

  const [title, setTitle] = useState("");
  const [scope, setScope] = useState<"department" | "employee">("department");
  const [departmentId, setDepartmentId] = useState<number | null>(null);
  const [assigneeId, setAssigneeId] = useState<number | null>(null);
  const [description, setDescription] = useState("");
  const [expected, setExpected] = useState("");
  const [priority, setPriority] = useState<"low" | "normal" | "high">("normal");
  const [requiresPhoto, setRequiresPhoto] = useState(false);
  const [requiresReview, setRequiresReview] = useState(false);
  const [shiftDate, setShiftDate] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [dueTime, setDueTime] = useState("");
  const [dueSeconds, setDueSeconds] = useState("00");
  // Расписание по дням недели: «каждый четверг». Пусто — без расписания,
  // тогда работает только срок. Понедельник — 1 (ISO), как в чек-листах.
  const [taskWeekdays, setTaskWeekdays] = useState<number[]>([]);

  const departments = departmentsQ.data ?? [];
  const employees = (employeesQ.data ?? []).filter((e) => e.is_active);

  // null — «без срока». Пустая дата означает именно это, а не «сегодня».
  const dueAt = useMemo(() => {
    if (!dueDate || !dueTime) return null;
    const sec = Math.max(0, Math.min(59, Number(dueSeconds) || 0));
    const hhmm = dueTime.length === 5 ? `${dueTime}:${String(sec).padStart(2, "0")}` : dueTime;
    const parsed = new Date(`${dueDate}T${hhmm}`);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }, [dueDate, dueTime, dueSeconds]);

  const create = useMutation({
    mutationFn: () => {
      if (!title.trim()) throw new Error(tx("Напиши, что нужно сделать."));
      if (scope === "department" && !departmentId) {
        throw new Error(tx("Выбери подразделение."));
      }
      if (scope === "employee" && !assigneeId) {
        throw new Error(tx("Выбери сотрудника."));
      }
      if (dueDate && !dueTime) {
        throw new Error(tx("Укажи время дедлайна или очисти дату."));
      }
      return createAdminTask({
        title: title.trim(),
        scope,
        department_id: scope === "department" ? departmentId : null,
        assignee_employee_id: scope === "employee" ? assigneeId : null,
        description: description.trim() || null,
        expected_result: expected.trim() || null,
        priority,
        requires_photo: requiresPhoto,
        requires_review: requiresReview,
        shift_date: shiftDate || null,
        due_at: dueAt ? dueAt.toISOString() : null,
        weekdays: taskWeekdays.length ? taskWeekdays : null,
      });
    },
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["hr-admin-tasks"] });
      void qc.invalidateQueries({ queryKey: ["hr-tasks"] });
      setTitle("");
      setDescription("");
      setExpected("");
      setTaskWeekdays([]);
      void showAlert(tx("Поручение создано — сотрудник увидит его в приложении."));
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const close = useMutation({
    mutationFn: (task: HrAdminTask) => setAdminTaskStatus(task.id, "done"),
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["hr-admin-tasks"] });
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  /** Быстрый срок: «через N минут от сейчас», секунды сохраняются. */
  const quickDue = (minutes: number) => {
    const at = new Date(Date.now() + minutes * 60_000);
    at.setSeconds(0, 0);
    setDueDate(localDate(at));
    setDueTime(localTime(at));
    setDueSeconds("00");
    haptic("light");
  };

  return (
    <SubScreen
      title={tx("Поручения")}
      subtitle={tx("Создать и закрыть · срок с точностью до секунды")}
      onBack={onBack}
    >
      <section className="rounded-card bg-tg-secondary-bg/60 p-3 space-y-3">
        <div className="text-sm font-semibold text-tg-text">{tx("Новое поручение")}</div>

        <label className="block text-xs text-tg-hint">{tx("Что сделать")}<input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            placeholder={tx("Проверить сроки на витрине")}
            className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg/60 px-3 text-sm text-tg-text"
          />
        </label>

        <div className="flex gap-1.5" role="tablist" aria-label={tx("Кому")}>
          {[
            { v: "department" as const, label: tx("Отделу") },
            { v: "employee" as const, label: tx("Сотруднику") },
          ].map((o) => (
            <button
              key={o.v}
              type="button"
              role="tab"
              aria-selected={scope === o.v}
              onClick={() => {
                haptic("selection");
                setScope(o.v);
              }}
              className={[
                "min-h-9 flex-1 rounded-tile text-xs",
                scope === o.v
                  ? "bg-tg-button text-tg-button-text"
                  : "bg-tg-bg/60 text-tg-hint",
              ].join(" ")}
            >
              {o.label}
            </button>
          ))}
        </div>

        {scope === "department" ? (
          <label className="block text-xs text-tg-hint">{tx("Подразделение")}<select
              value={departmentId ?? ""}
              onChange={(e) => setDepartmentId(e.target.value ? Number(e.target.value) : null)}
              className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            >
              <option value="">{tx("— выбери —")}</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.emoji ? `${d.emoji} ` : ""}
                  {d.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label className="block text-xs text-tg-hint">{tx("Сотрудник")}<select
              value={assigneeId ?? ""}
              onChange={(e) => setAssigneeId(e.target.value ? Number(e.target.value) : null)}
              className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            >
              <option value="">{tx("— выбери —")}</option>
              {employees.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.display_name}
                  {e.position ? ` · ${e.position}` : ""}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="block text-xs text-tg-hint">{tx("Описание (необязательно)")}<textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            maxLength={1000}
            className="mt-1 w-full rounded-tile bg-tg-bg/60 p-2 text-sm text-tg-text"
          />
        </label>

        <label className="block text-xs text-tg-hint">{tx("Что должно получиться (необязательно)")}<input
            value={expected}
            onChange={(e) => setExpected(e.target.value)}
            maxLength={300}
            className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg/60 px-3 text-sm text-tg-text"
          />
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="block text-xs text-tg-hint">{tx("Смена (необязательно)")}<input
              type="date"
              value={shiftDate}
              onChange={(e) => setShiftDate(e.target.value)}
              className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            />
          </label>
          <label className="block text-xs text-tg-hint">{tx("Приоритет")}<select
              value={priority}
              onChange={(e) =>
                setPriority(e.target.value as "low" | "normal" | "high")
              }
              className="mt-1 min-h-11 w-full rounded-tile bg-tg-bg/60 px-2 text-sm text-tg-text"
            >
              <option value="low">{tx("низкий")}</option>
              <option value="normal">{tx("обычный")}</option>
              <option value="high">{tx("высокий")}</option>
            </select>
          </label>
        </div>

        <div>
          <div className="text-xs text-tg-hint">{tx("Повторяется по дням (необязательно)")}</div>
          <div className="mt-1 flex gap-1">
            {WEEKDAY_OPTIONS.map(({ day, short, full }) => {
              const selected = taskWeekdays.includes(day);
              return (
                <button
                  key={day}
                  type="button"
                  aria-pressed={selected}
                  aria-label={tx(full)}
                  onClick={() => {
                    haptic("selection");
                    setTaskWeekdays((current) =>
                      selected
                        ? current.filter((d) => d !== day)
                        : [...current, day].sort((a, b) => a - b),
                    );
                  }}
                  className={[
                    "min-h-9 flex-1 rounded-tile text-xs transition-colors",
                    selected
                      ? "bg-tg-button text-tg-button-text"
                      : "bg-tg-bg/60 text-tg-hint",
                  ].join(" ")}
                >
                  {tx(short)}
                </button>
              );
            })}
          </div>
          <p className="mt-1 text-2xs text-tg-hint">
            {taskWeekdays.length
              ? tx("В остальные дни поручение остаётся в списке, но помечено как не сегодняшнее.")
              : tx("Ничего не выбрано — срок работает как обычно.")}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <Check
            checked={requiresPhoto}
            onChange={setRequiresPhoto}
            label={tx("Нужен фотоотчёт")}
          />
          <Check
            checked={requiresReview}
            onChange={setRequiresReview}
            label={tx("С приёмкой")}
          />
        </div>

        <div className="rounded-tile bg-tg-bg/50 p-2.5">
          <div className="text-xs text-tg-hint">{tx("Срок — дата, время и секунды. Пусто = без срока.")}</div>
          <div className="mt-2 grid grid-cols-[1.4fr_1fr_0.7fr] gap-2">
            <label className="block text-xs text-tg-hint">{tx("Дата")}<input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text"
              />
            </label>
            <label className="block text-xs text-tg-hint">{tx("Время")}<input
                type="time"
                step={1}
                value={dueTime}
                onChange={(e) => setDueTime(e.target.value)}
                className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text"
              />
            </label>
            <label className="block text-xs text-tg-hint">{tx("Сек.")}<input
                inputMode="numeric"
                value={dueSeconds}
                onChange={(e) => setDueSeconds(e.target.value.replace(/\D/g, "").slice(0, 2))}
                className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text tabular-nums"
              />
            </label>
          </div>

          <div className="mt-2 flex flex-wrap gap-1.5">
            {[
              { label: tx("+30 мин"), min: 30 },
              { label: tx("+1 час"), min: 60 },
              { label: tx("до конца смены"), min: 8 * 60 },
              { label: tx("завтра"), min: 24 * 60 },
            ].map((q) => (
              <button
                key={q.label}
                type="button"
                onClick={() => quickDue(q.min)}
                className="min-h-8 rounded-full bg-tg-secondary-bg px-2.5 text-xs text-tg-text"
              >
                {q.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => {
                setDueDate("");
                setDueTime("");
                setDueSeconds("00");
              }}
              className="min-h-8 rounded-full bg-tg-secondary-bg px-2.5 text-xs text-tg-hint"
            >{tx("без срока")}</button>
          </div>

          <div className="mt-2 text-xs text-tg-hint">
            {dueAt
              ? tx("Срок: {when}", { when: formatPrecise(dueAt) })
              : tx("Срок не задан — планировщик не будет напоминать.")}
          </div>
        </div>

        <button
          type="button"
          disabled={create.isPending}
          onClick={() => create.mutate()}
          className="min-h-11 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
        >
          {create.isPending ? tx("Создаю…") : tx("Создать поручение")}
        </button>
      </section>

      <section className="space-y-2">
        <div className="text-sm font-semibold text-tg-text">{tx("Последние поручения")}</div>
        {(tasksQ.data ?? []).slice(0, 20).map((task) => (
          <article key={task.id} className="rounded-card bg-tg-secondary-bg/60 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-sm font-medium text-tg-text break-words">
                  {task.title}
                </div>
                <div className="mt-1 text-xs text-tg-hint">
                  {task.due_at ? (
                    <>
                      <InlineIcon name="clock" />
                      {formatPrecise(new Date(task.due_at))}
                    </>
                  ) : (
                    tx("без срока")
                  )}
                  {task.requires_photo && (
                    <>
                      {" · "}
                      <InlineIcon name="camera" />
                    </>
                  )}
                  {task.photos?.length
                    ? tx(" · фото {count}", { count: task.photos.length })
                    : ""}
                  {task.schedule_label && (
                    <>
                      {" · "}
                      <InlineIcon name="calendar" />
                      {task.schedule_label}
                    </>
                  )}
                </div>
              </div>
              <span className="shrink-0 rounded-full bg-tg-bg/60 px-2 py-0.5 text-xs text-tg-hint">
                {task.status}
              </span>
            </div>
            {task.status !== "done" && (
              <button
                type="button"
                disabled={close.isPending}
                onClick={async () => {
                  const ok = await showConfirm(
                    tx("Закрыть «{title}»?", { title: task.title }),
                  );
                  if (ok) close.mutate(task);
                }}
                className="mt-2 min-h-9 rounded-tile bg-tg-bg/60 px-3 text-xs text-tg-text"
              >{tx("Зачесть выполненным")}</button>
            )}
          </article>
        ))}
        {tasksQ.data?.length === 0 && (
          <div className="rounded-card bg-tg-secondary-bg/40 p-3 text-xs text-tg-hint">{tx("Пока пусто — создай первое поручение выше.")}</div>
        )}
      </section>
    </SubScreen>
  );
}

function Check({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => {
        haptic("selection");
        onChange(!checked);
      }}
      className={[
        "min-h-9 rounded-tile px-3 text-xs",
        checked ? "bg-tg-button text-tg-button-text" : "bg-tg-bg/60 text-tg-hint",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

// Дни недели для расписания поручения (ISO: 1 — понедельник).
const WEEKDAY_OPTIONS: { day: number; short: string; full: string }[] = [
  { day: 1, short: "Пн", full: "понедельник" },
  { day: 2, short: "Вт", full: "вторник" },
  { day: 3, short: "Ср", full: "среда" },
  { day: 4, short: "Чт", full: "четверг" },
  { day: 5, short: "Пт", full: "пятница" },
  { day: 6, short: "Сб", full: "суббота" },
  { day: 7, short: "Вс", full: "воскресенье" },
];

/** Локальная дата `YYYY-MM-DD` — без UTC-сдвига `toISOString()`. */
function localDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Локальное время `HH:MM` (секунды вводим отдельным полем). */
function localTime(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** «20.10.2026 17:30:05» — секунды видны, чтобы точность не была фикцией. */
function formatPrecise(d: Date): string {
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
