import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  TASK_MODE_LABEL,
  fetchEmployee,
  fetchTasks,
  reportTaskIssue,
  runTaskAction,
  type HrTask,
  type TaskAction,
  type TaskStatus,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import Badge from "@/features/hr/Badge";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import { useUI } from "@/store/ui";

/**
 * SemiTaskBot: «Мои задачи» — главный экран смены.
 *
 * Здесь только личные поручения (scope=employee + поручения своего
 * подразделения): сервер сам решает, что показывать, поэтому экран не
 * фильтрует данные повторно и не имеет доступа к чужим задачам.
 *
 * Порядок действий: принять → начать → выполнить. «Не успеваю» открывает
 * встроенную форму причины: она не отменяет поручение, а отправляет
 * руководителю объяснение (и, если указан новый срок, запускает отсчёт заново).
 */

const STATUS_LABEL: Record<TaskStatus, string> = {
  new: "Новое",
  accepted: "Принято",
  in_progress: "В работе",
  on_review: "На проверке",
  rework: "На доработке",
  done: "Выполнено",
  overdue: "Просрочено",
  failed: "Не выполнено",
};

const STATUS_CLASS: Record<TaskStatus, string> = {
  new: "bg-tg-link/15 text-tg-link",
  accepted: "bg-tg-link/15 text-tg-link",
  in_progress: "bg-status-maybe/20 text-status-maybe",
  on_review: "bg-tg-link/15 text-tg-link",
  rework: "bg-status-busy/20 text-status-busy",
  done: "bg-status-free/20 text-status-free",
  overdue: "bg-status-busy/20 text-status-busy",
  failed: "bg-status-busy/20 text-status-busy",
};

/** Личный статус: в групповом поручении агрегат не отвечает «сделал ли я». */
function ownStatus(task: HrTask): TaskStatus {
  return task.my_status ?? task.status;
}

/** «смена 14.05» из ISO-даты смены. */
function fmtShift(iso: string | null): string | null {
  if (!iso) return null;
  const [y, m, d] = iso.split("-");
  return y && m && d ? `${d}.${m}` : null;
}

const PRIORITY_LABEL: Record<HrTask["priority"], string> = {
  low: "низкий",
  normal: "обычный",
  high: "высокий",
};

const ISSUE_REASONS: { code: string; label: string }[] = [
  { code: "no_time", label: "Не хватает времени" },
  { code: "need_help", label: "Нужна помощь" },
  { code: "no_materials", label: "Нет материалов/доступа" },
  { code: "equipment", label: "Оборудование не работает" },
  { code: "other", label: "Другое" },
];

/** «Сегодня 18:00», «Завтра 09:30», иначе «14.05 18:00». */
function fmtDue(iso: string | null): string {
  if (!iso) return "без срока";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "без срока";
  const time = d.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
  const today = new Date();
  const dayOf = (x: Date) =>
    new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((dayOf(d) - dayOf(today)) / 86_400_000);
  if (diff === 0) return `сегодня ${time}`;
  if (diff === 1) return `завтра ${time}`;
  if (diff === -1) return `вчера ${time}`;
  return `${d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })} ${time}`;
}

export default function MyTasksScreen() {
  const qc = useQueryClient();
  const setTab = useUI((s) => s.setTab);
  const [showClosed, setShowClosed] = useState(false);
  const [issueFor, setIssueFor] = useState<number | null>(null);

  const meQ = useQuery({ queryKey: ["hr-employee"], queryFn: fetchEmployee });
  const tasksQ = useQuery({
    queryKey: ["hr-tasks", showClosed],
    queryFn: () => fetchTasks(showClosed),
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["hr-tasks"] });
    void qc.invalidateQueries({ queryKey: ["hr-feed"] });
  };

  const action = useMutation({
    mutationFn: ({ id, act }: { id: number; act: TaskAction }) =>
      runTaskAction(id, act),
    onSuccess: () => {
      haptic("light");
      invalidate();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  if (meQ.isError)
    return <ErrorState error={meQ.error} onRetry={() => void meQ.refetch()} />;
  if (tasksQ.isError)
    return (
      <ErrorState error={tasksQ.error} onRetry={() => void tasksQ.refetch()} />
    );

  const tasks = tasksQ.data ?? [];
  // «Активные» считаем по своему статусу: в режиме «каждый сам» задача ещё
  // открыта для коллег, хотя я свою часть уже закрыл. `on_review` тоже
  // активна: работа сдана, но пока не принята — это ещё не закрыто.
  const open = tasks.filter((t) => {
    const status = ownStatus(t);
    return status !== "done" && status !== "failed";
  });
  const overdue = open.filter((t) => t.is_overdue).length;

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h1 className="text-lg font-semibold text-tg-text">Мои задачи</h1>          <span className="flex items-center gap-2">
            {meQ.data && (
              <span className="flex items-center gap-1.5 text-xs text-tg-hint">
                <span className="truncate">{meQ.data.display_name}</span>
                <Badge
                  text={meQ.data.badge}
                  emoji={meQ.data.badge_emoji}
                  demo={meQ.data.is_demo}
                />
              </span>
            )}
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setTab("standards");
              }}
              className="min-h-8 min-w-8 rounded-lg bg-tg-secondary-bg text-base leading-none"
              aria-label="База стандартов"
              title="База стандартов"
            >
              📚
            </button>
            {meQ.data?.is_aup && (
              <button
                type="button"
                onClick={() => {
                  haptic("selection");
                  setTab("review");
                }}
                className="min-h-8 min-w-8 rounded-lg bg-tg-secondary-bg text-base leading-none"
                aria-label="Приёмка работ"
                title="Приёмка работ"
              >
                🔍
              </button>
            )}
            {/* Конец смены начинается здесь: сдача того, что осталось. */}
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setTab("handovers");
              }}
              className="min-h-8 min-w-8 rounded-lg bg-tg-secondary-bg text-base leading-none"
              aria-label="Передача смены"
              title="Передача смены"
            >
              🌙
            </button>
          </span>
        </div>
        <p className="mt-1 text-xs text-tg-hint">
          {open.length === 0
            ? "Активных поручений нет — смена закрыта."
            : `Активных: ${open.length}${overdue ? ` · просрочено: ${overdue}` : ""}`}
        </p>
        <div className="mt-3 flex items-center gap-1.5">
          {[
            { v: false, label: "Активные" },
            { v: true, label: "Все" },
          ].map((o) => (
            <button
              key={String(o.v)}
              type="button"
              onClick={() => {
                haptic("light");
                setShowClosed(o.v);
              }}
              className={[
                "min-h-8 rounded-full px-3 text-xs transition-colors",
                showClosed === o.v
                  ? "bg-tg-button text-tg-button-text"
                  : "bg-tg-secondary-bg text-tg-hint",
              ].join(" ")}
            >
              {o.label}
            </button>
          ))}
          {/* Журнал проблем не в нижней полосе: проблем меньше, чем задач, и
              заводить их бегут именно отсюда. */}
          <button
            type="button"
            onClick={() => {
              haptic("selection");
              setTab("issues");
            }}
            className="ml-auto min-h-8 rounded-full bg-tg-secondary-bg px-2.5 text-xs text-tg-hint"
          >
            🛠 Проблемы
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {tasksQ.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {!tasksQ.isLoading && tasks.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="text-4xl" aria-hidden>
              🎯
            </div>
            <div className="mt-2 text-sm font-medium text-tg-text">
              Поручений нет
            </div>
            <div className="mt-1 text-xs text-tg-hint">
              Как только руководитель поставит задачу, она появится здесь и
              придёт в чат.
            </div>
          </div>
        )}

        {tasks.map((t) => (
          <TaskCard
            key={t.id}
            task={t}
            busy={action.isPending}
            issueOpen={issueFor === t.id}
            onToggleIssue={() => {
              haptic("light");
              setIssueFor(issueFor === t.id ? null : t.id);
            }}
            onAction={(act) => action.mutate({ id: t.id, act })}
            onIssued={() => {
              setIssueFor(null);
              invalidate();
            }}
          />
        ))}
      </div>
    </div>
  );
}

function TaskCard({
  task,
  busy,
  issueOpen,
  onToggleIssue,
  onAction,
  onIssued,
}: {
  task: HrTask;
  busy: boolean;
  issueOpen: boolean;
  onToggleIssue: () => void;
  onAction: (a: TaskAction) => void;
  onIssued: () => void;
}) {
  const status = ownStatus(task);
  const closed = status === "done" || status === "failed";
  const shift = fmtShift(task.shift_date);
  const group = task.progress_total > 1;
  return (
    <article className="rounded-xl bg-tg-secondary-bg/60 p-3">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-semibold text-tg-text break-words">
          {task.title}
        </h2>
        <span
          className={[
            "shrink-0 rounded-full px-2 py-0.5 text-[11px]",
            STATUS_CLASS[status],
          ].join(" ")}
        >
          {STATUS_LABEL[status]}
        </span>
      </div>

      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-tg-hint">
        <span>⏰ {fmtDue(task.due_at)}</span>
        {shift && <span>🗓 смена {shift}</span>}
        {task.priority !== "normal" && (
          <span>приоритет: {PRIORITY_LABEL[task.priority]}</span>
        )}
        {task.requires_photo && <span>📷 нужен фотоотчёт</span>}
        {task.requires_review && <span>🔍 с приёмкой</span>}
        {task.is_overdue && !closed && (
          <span className="text-status-busy">просрочено</span>
        )}
      </div>

      {group && (
        <div className="mt-1.5 text-[11px] text-tg-hint">
          👥 {TASK_MODE_LABEL[task.mode]} · сделали {task.progress_done} из{" "}
          {task.progress_total}
        </div>
      )}
      {task.my_part && (
        <div className="mt-1 text-[11px] text-tg-text/90">
          Моя часть: {task.my_part}
        </div>
      )}

      {task.description && (
        <p className="mt-2 text-xs text-tg-text/90 whitespace-pre-wrap break-words">
          {task.description}
        </p>
      )}
      {task.expected_result && (
        <p className="mt-1 text-xs text-tg-hint">
          <span className="text-tg-hint/80">Результат: </span>
          {task.expected_result}
        </p>
      )}

      {!closed && status === "on_review" && (
        <div className="mt-3 rounded-lg bg-tg-bg/60 px-2.5 py-2 text-[11px] text-tg-hint">
          Работа сдана — ждёт приёмки руководителя.
        </div>
      )}

      {!closed && status !== "on_review" && (
        <div className="mt-3 flex flex-wrap gap-2">
          {status === "new" && (
            <ActionButton disabled={busy} onClick={() => onAction("accept")}>
              Принять
            </ActionButton>
          )}
          {(status === "new" ||
            status === "accepted" ||
            status === "rework") && (
            <ActionButton disabled={busy} onClick={() => onAction("start")}>
              {status === "rework" ? "Взять в работу" : "Начать"}
            </ActionButton>
          )}
          {(status === "in_progress" ||
            status === "overdue" ||
            status === "rework") && (
            <ActionButton disabled={busy} onClick={() => onAction("done")}>
              {task.requires_photo
                ? "Отметить (фото — в чат)"
                : task.requires_review
                  ? "Сдать на проверку"
                  : "Выполнено"}
            </ActionButton>
          )}
          <ActionButton disabled={busy} variant="ghost" onClick={onToggleIssue}>
            {issueOpen ? "Отмена" : "Не успеваю"}
          </ActionButton>
        </div>
      )}


      {closed && task.done_at && (
        <div className="mt-2 text-[11px] text-tg-hint">
          Закрыто: {new Date(task.done_at).toLocaleString("ru-RU")}
        </div>
      )}

      {issueOpen && <IssueForm taskId={task.id} onDone={onIssued} />}
    </article>
  );
}

function IssueForm({ taskId, onDone }: { taskId: number; onDone: () => void }) {
  const [reason, setReason] = useState(ISSUE_REASONS[0].code);
  const [comment, setComment] = useState("");
  const [eta, setEta] = useState("");

  const m = useMutation({
    mutationFn: () =>
      reportTaskIssue(taskId, {
        reason_code: reason,
        comment: comment.trim() || null,
        eta_at: eta ? new Date(eta).toISOString() : null,
      }),
    onSuccess: () => {
      haptic("success");
      void showAlert(
        "Руководителю отправлено объяснение. Срок отсчитывается заново.",
      );
      onDone();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  return (
    <div className="mt-3 rounded-lg bg-tg-bg/60 p-3">
      <label className="block text-[11px] text-tg-hint">
        Причина
        <select
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="mt-1 min-h-10 w-full rounded-lg bg-tg-secondary-bg px-2 text-sm text-tg-text"
        >
          {ISSUE_REASONS.map((r) => (
            <option key={r.code} value={r.code}>
              {r.label}
            </option>
          ))}
        </select>
      </label>

      <label className="mt-2 block text-[11px] text-tg-hint">
        Когда сможешь закончить (необязательно)
        <input
          type="datetime-local"
          value={eta}
          onChange={(e) => setEta(e.target.value)}
          className="mt-1 min-h-10 w-full rounded-lg bg-tg-secondary-bg px-2 text-sm text-tg-text"
        />
      </label>

      <label className="mt-2 block text-[11px] text-tg-hint">
        Комментарий
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={2}
          maxLength={500}
          placeholder="Что именно мешает?"
          className="mt-1 w-full rounded-lg bg-tg-secondary-bg p-2 text-sm text-tg-text"
        />
      </label>

      <button
        type="button"
        disabled={m.isPending}
        onClick={() => m.mutate()}
        className="mt-3 min-h-10 w-full rounded-lg bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
      >
        Отправить руководителю
      </button>
    </div>
  );
}

function ActionButton({
  children,
  onClick,
  disabled,
  variant = "primary",
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  variant?: "primary" | "ghost";
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={[
        "min-h-10 rounded-lg px-3 text-xs font-medium transition-transform active:scale-[0.98] disabled:opacity-50",
        variant === "primary"
          ? "bg-tg-button text-tg-button-text"
          : "bg-tg-secondary-bg text-tg-text",
      ].join(" ")}
    >
      {children}
    </button>
  );
}
