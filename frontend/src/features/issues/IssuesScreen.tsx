import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ISSUE_CATEGORY_ICON,
  ISSUE_CATEGORY_LABEL,
  ISSUE_SEVERITY_LABEL,
  ISSUE_STATUS_LABEL,
  commentIssue,
  createIssue,
  fetchIssue,
  fetchIssues,
  setIssueStatus,
  updateIssue,
  type HrIssue,
  type HrIssueDetail,
  type IssueCategory,
  type IssueSeverity,
  type IssueStatus,
} from "@/api/issues";
import { fetchEmployee } from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import BottomSheet from "@/features/actions/BottomSheet";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import { CardSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import { useUI } from "@/store/ui";

import {
  currentIntlLocale,
  currentLocale,
  tx as txIn,
  useTx,
} from "@/i18n";
/**
 * Журнал операционных проблем смены.
 *
 * Зачем отдельно от «Мои задачи»: проблема не обязана родиться из поручения и
 * не умирает вместе с ним. Здесь её можно завести одной строкой, увидеть, что с
 * ней происходит у коллег, передать ответственному и закрыть тогда, когда её
 * реально решили. Права считает сервер (`can_edit`/`can_close`/`can_reopen`),
 * экран только прячет то, что бэкенд всё равно отклонит.
 */

const SEVERITY_CLASS: Record<IssueSeverity, string> = {
  low: "bg-tg-secondary-bg text-tg-hint",
  normal: "bg-status-maybe/20 text-status-maybe",
  high: "bg-status-busy/20 text-status-busy",
  critical: "bg-status-busy text-white",
};

const STATUS_CLASS: Record<IssueStatus, string> = {
  open: "bg-status-busy/15 text-status-busy",
  in_progress: "bg-status-maybe/20 text-status-maybe",
  resolved: "bg-status-free/20 text-status-free",
  cancelled: "bg-tg-secondary-bg text-tg-hint",
};

const SEVERITIES: IssueSeverity[] = ["low", "normal", "high", "critical"];
const CATEGORIES = Object.keys(ISSUE_CATEGORY_LABEL) as IssueCategory[];

type View = "open" | "all" | "mine";

const VIEW_OPTIONS: { value: View; label: string }[] = [
  { value: "open", label: "Активные" },
  { value: "all", label: "Все" },
  { value: "mine", label: "Мои" },
];

/** «4 ч», «3 дня» — сколько карточка висит. */
function fmtAge(hours: number): string {
  const locale = currentLocale();
  if (hours < 1) return txIn(locale, "меньше часа");
  if (hours < 24) return `${Math.round(hours)} ${txIn(locale, "ч")}`;
  const days = Math.round(hours / 24);
  const mod10 = days % 10;
  const mod100 = days % 100;
  // В английском две формы; в русском — три. Формы живут в словаре, чтобы
  // «days» не появлялся из кода, который не знает про локаль.
  const word =
    locale === "en"
      ? txIn(locale, days === 1 ? "день" : "дней")
      : mod10 === 1 && mod100 !== 11
        ? txIn(locale, "день")
        : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
          ? txIn(locale, "дня")
          : txIn(locale, "дней");
  return `${days} ${word}`;
}

function fmtMoment(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(currentIntlLocale(), {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function IssuesScreen() {
  const { tx } = useTx();
  const setTab = useUI((s) => s.setTab);
  const qc = useQueryClient();
  const [view, setView] = useState<View>("open");
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  const issuesQ = useQuery({
    queryKey: ["hr-issues", view],
    queryFn: () =>
      fetchIssues({
        includeClosed: view === "all",
        mine: view === "mine",
      }),
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["hr-issues"] });
    void qc.invalidateQueries({ queryKey: ["hr-issue"] });
  };

  if (issuesQ.isError) {
    return (
      <ErrorState
        error={issuesQ.error}
        onRetry={() => void issuesQ.refetch()}
        title={tx("Журнал проблем не открылся")}
      />
    );
  }

  const data = issuesQ.data;
  const items = data?.items ?? [];
  const summary = data?.summary;

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <div className="flex items-start gap-2">
          <button
            type="button"
            onClick={() => {
              haptic("light");
              setTab("tasks");
            }}
            className="-ml-1 min-h-11 min-w-11 rounded-tile text-lg text-tg-hint"
            aria-label={tx("Назад к задачам")}
          >
            ‹
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="flex items-center gap-2 text-lg font-semibold text-tg-text">
              <Icon name="alert" size={18} />{tx("Журнал проблем")}</h1>
            <p className="mt-0.5 text-xs text-tg-hint">
              {summary
                ? summarize(summary.total_open, summary.attention)
                : tx("Что на смене пошло не так — и кто это закрывает.")}
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              haptic("light");
              setCreating(true);
            }}
            className="min-h-9 shrink-0 rounded-tile bg-tg-button px-3 text-xs font-medium text-tg-button-text"
          >{tx("+ Сообщить")}</button>
        </div>

        <div className="mt-3 flex gap-1.5">
          {VIEW_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                haptic("light");
                setView(option.value);
              }}
              className={[
                "min-h-8 rounded-full px-3 text-xs transition-colors",
                view === option.value
                  ? "bg-tg-button text-tg-button-text"
                  : "bg-tg-secondary-bg text-tg-hint",
              ].join(" ")}
            >
              {tx(option.label)}
            </button>
          ))}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2.5">
        {issuesQ.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {!issuesQ.isLoading && items.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <Icon name="alert" size={34} className="text-tg-hint" />
            <div className="mt-2 text-sm font-medium text-tg-text">
              {view === "mine" ? tx("У тебя открытых проблем нет") : tx("Журнал пуст")}
            </div>
            <div className="mt-1 text-xs text-tg-hint">{tx(
              "Сломалось оборудование, закончились расходники, гость недоволен — заведи карточку, чтобы смена не теряла проблему.",
            )}</div>
          </div>
        )}

        {items.map((issue) => (
          <IssueCard
            key={issue.id}
            issue={issue}
            onClick={() => {
              haptic("selection");
              setSelected(issue.id);
            }}
          />
        ))}
      </div>

      {creating && (
        <CreateIssueSheet
          onClose={() => setCreating(false)}
          onCreated={(created) => {
            setCreating(false);
            invalidate();
            setSelected(created.id);
          }}
        />
      )}

      {selected !== null && (
        <IssueSheet
          issueId={selected}
          onClose={() => {
            setSelected(null);
            invalidate();
          }}
        />
      )}
    </div>
  );
}

function summarize(open: number, attention: number): string {
  const locale = currentLocale();
  if (open === 0) return txIn(locale, "Открытых проблем нет — смена чистая.");
  return [
    txIn(locale, "Открыто: {count}", { count: open }),
    attention
      ? txIn(locale, "требуют внимания: {count}", { count: attention })
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function IssueCard({ issue, onClick }: { issue: HrIssue; onClick: () => void }) {
  const { tx } = useTx();
  const closed = issue.status === "resolved" || issue.status === "cancelled";
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-card bg-tg-secondary-bg/60 p-3 text-left transition-transform active:scale-[0.99]"
    >
      <div className="flex items-start gap-2">
        <span className="text-base leading-5" aria-hidden>
          {ISSUE_CATEGORY_ICON[issue.category]}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h2
              className={[
                "text-sm font-semibold break-words",
                closed ? "text-tg-hint line-through" : "text-tg-text",
              ].join(" ")}
            >
              {issue.title}
            </h2>
            <span
              className={[
                "shrink-0 rounded-full px-2 py-0.5 text-xs",
                STATUS_CLASS[issue.status],
              ].join(" ")}
            >
              {tx(ISSUE_STATUS_LABEL[issue.status])}
            </span>
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-tg-hint">
            <span
              className={[
                "rounded-full px-1.5 py-0.5",
                SEVERITY_CLASS[issue.severity],
              ].join(" ")}
            >
              {tx(ISSUE_SEVERITY_LABEL[issue.severity])}
            </span>
            <span>{tx(ISSUE_CATEGORY_LABEL[issue.category])}</span>
            {issue.zone && <span>· {issue.zone}</span>}
            {issue.department_name && <span>· {issue.department_name}</span>}
          </div>

          <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-tg-hint">
            <span>{tx("висит {age}", { age: fmtAge(issue.age_hours) })}</span>
            {issue.created_by_name && (
              <span>{tx("· завёл {name}", { name: issue.created_by_name })}</span>
            )}
            {issue.assignee_name && (
              <span className="text-tg-text/80">
                {tx("· на {name}", { name: issue.assignee_name })}
              </span>
            )}
            {issue.task_id && <span>{tx("· из поручения")}</span>}
          </div>
        </div>
      </div>
    </button>
  );
}

function CreateIssueSheet({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (issue: HrIssueDetail) => void;
}) {
  const { tx } = useTx();
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<IssueCategory>("equipment");
  const [severity, setSeverity] = useState<IssueSeverity>("normal");
  const [zone, setZone] = useState("");
  const [description, setDescription] = useState("");

  const m = useMutation({
    mutationFn: () =>
      createIssue({
        title: title.trim(),
        category,
        severity,
        zone: zone.trim() || null,
        description: description.trim() || null,
      }),
    onSuccess: (created) => {
      haptic("success");
      onCreated(created);
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  return (
    <BottomSheet title={tx("Новая проблема")} onClose={onClose}>
      <label className="block text-xs text-tg-hint">{tx("Что случилось")}<input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
          placeholder={tx("Например: не работает терминал на баре")}
          className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text"
        />
      </label>

      <div className="mt-3 text-xs text-tg-hint">{tx("Категория")}</div>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {CATEGORIES.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => {
              haptic("light");
              setCategory(c);
            }}
            className={[
              "min-h-8 rounded-full px-2.5 text-xs transition-colors",
              category === c
                ? "bg-tg-button text-tg-button-text"
                : "bg-tg-secondary-bg text-tg-hint",
            ].join(" ")}
          >
            {ISSUE_CATEGORY_ICON[c]} {tx(ISSUE_CATEGORY_LABEL[c])}
          </button>
        ))}
      </div>

      <div className="mt-3 text-xs text-tg-hint">{tx("Насколько срочно")}</div>
      <div className="mt-1 grid grid-cols-4 gap-1.5">
        {SEVERITIES.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              haptic("light");
              setSeverity(s);
            }}
            className={[
              "min-h-8 rounded-tile px-1 text-xs transition-colors",
              severity === s
                ? "bg-tg-button text-tg-button-text"
                : "bg-tg-secondary-bg text-tg-hint",
            ].join(" ")}
          >
            {tx(ISSUE_SEVERITY_LABEL[s])}
          </button>
        ))}
      </div>

      <label className="mt-3 block text-xs text-tg-hint">{tx("Где (необязательно)")}<input
          value={zone}
          onChange={(e) => setZone(e.target.value)}
          maxLength={64}
          placeholder={tx("Зал, кухня, бар, склад…")}
          className="mt-1 min-h-11 w-full rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text"
        />
      </label>

      <label className="mt-3 block text-xs text-tg-hint">{tx("Подробности (необязательно)")}<textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          maxLength={2000}
          placeholder={tx("Что уже пробовали, кому сказали, что нужно для решения")}
          className="mt-1 w-full rounded-tile bg-tg-secondary-bg p-2 text-sm text-tg-text"
        />
      </label>

      <button
        type="button"
        disabled={m.isPending || title.trim().length === 0}
        onClick={() => m.mutate()}
        className="mt-4 min-h-11 w-full rounded-tile bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
      >
        {m.isPending ? tx("Записываю…") : tx("Завести карточку")}
      </button>
      <p className="mt-2 text-center text-xs text-tg-hint">{tx(
        "Руководитель отдела увидит проблему в колокольчике и в журнале. В чат сообщение не уходит — это не срочный алерт.",
      )}</p>
    </BottomSheet>
  );
}

function IssueSheet({
  issueId,
  onClose,
}: {
  issueId: number;
  onClose: () => void;
}) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const [comment, setComment] = useState("");

  const detailQ = useQuery({
    queryKey: ["hr-issue", issueId],
    queryFn: () => fetchIssue(issueId),
  });
  const meQ = useQuery({ queryKey: ["hr-employee"], queryFn: fetchEmployee });

  const apply = (updated: HrIssueDetail) => {
    qc.setQueryData(["hr-issue", issueId], updated);
    haptic("success");
    void qc.invalidateQueries({ queryKey: ["hr-issues"] });
  };

  const statusM = useMutation({
    mutationFn: (next: IssueStatus) => setIssueStatus(issueId, next),
    onSuccess: apply,
    onError: (e) => void showAlert(humanizeApiError(e)),
  });
  const commentM = useMutation({
    mutationFn: () => commentIssue(issueId, comment.trim()),
    onSuccess: (updated) => {
      setComment("");
      apply(updated);
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });
  const assignM = useMutation({
    mutationFn: (employeeId: number | null) =>
      updateIssue(issueId, {
        assignee_employee_id: employeeId,
        assignee_set: true,
      }),
    onSuccess: apply,
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const issue = detailQ.data;
  const meId = meQ.data?.id ?? null;
  const busy = statusM.isPending || commentM.isPending || assignM.isPending;

  return (
    <BottomSheet title={issue?.title ?? tx("Проблема")} onClose={onClose}>
      {detailQ.isLoading && <CardSkeleton />}
      {detailQ.isError && (
        <ErrorState
          error={detailQ.error}
          onRetry={() => void detailQ.refetch()}
        />
      )}

      {issue && (
        <>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-tg-hint">
            <span
              className={[
                "rounded-full px-2 py-0.5",
                STATUS_CLASS[issue.status],
              ].join(" ")}
            >
              {tx(ISSUE_STATUS_LABEL[issue.status])}
            </span>
            <span
              className={[
                "rounded-full px-2 py-0.5",
                SEVERITY_CLASS[issue.severity],
              ].join(" ")}
            >
              {tx(ISSUE_SEVERITY_LABEL[issue.severity])}
            </span>
            <span>
              {ISSUE_CATEGORY_ICON[issue.category]}{" "}
              {tx(ISSUE_CATEGORY_LABEL[issue.category])}
            </span>
            {issue.zone && <span>· {issue.zone}</span>}
            {issue.department_name && <span>· {issue.department_name}</span>}
          </div>

          {issue.description && (
            <p className="mt-2 whitespace-pre-wrap break-words text-sm text-tg-text/90">
              {issue.description}
            </p>
          )}

          <div className="mt-2 text-xs text-tg-hint">
            {tx("Завёл {name} · смена {date} · висит {age}", {
              name: issue.created_by_name ?? "—",
              date: issue.shift_date,
              age: fmtAge(issue.age_hours),
            })}
            {issue.assignee_name
              ? tx(" · ответственный: {name}", { name: issue.assignee_name })
              : ""}
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {issue.status === "open" && issue.can_edit && (
              <ActionButton
                disabled={busy}
                onClick={() => statusM.mutate("in_progress")}
              >{tx("Взять в работу")}</ActionButton>
            )}
            {issue.can_close &&
              (issue.status === "open" || issue.status === "in_progress") && (
                <>
                  <ActionButton
                    disabled={busy}
                    onClick={() => statusM.mutate("resolved")}
                  >{tx("Решено")}</ActionButton>
                  <ActionButton
                    variant="ghost"
                    disabled={busy}
                    onClick={() => statusM.mutate("cancelled")}
                  >{tx("Снять")}</ActionButton>
                </>
              )}
            {issue.can_reopen &&
              (issue.status === "resolved" || issue.status === "cancelled") && (
                <ActionButton
                  disabled={busy}
                  onClick={() => statusM.mutate("open")}
                >{tx("Переоткрыть")}</ActionButton>
              )}
            {meId !== null &&
              issue.assignee_employee_id !== meId &&
              (issue.status === "open" || issue.status === "in_progress") &&
              issue.can_edit && (
                <ActionButton
                  variant="ghost"
                  disabled={busy}
                  onClick={() => assignM.mutate(meId)}
                >{tx("Назначить на себя")}</ActionButton>
              )}
          </div>

          <h3 className="mt-4 text-sm font-semibold text-tg-text">{tx("История")}</h3>
          <ol className="mt-2 space-y-2">
            {issue.events.map((event) => (
              <li
                key={event.id}
                className="rounded-tile bg-tg-secondary-bg/60 px-3 py-2 text-xs"
              >
                <div className="text-xs text-tg-hint">
                  {fmtMoment(event.at)} · {event.by_name ?? tx("система")}
                </div>
                <div className="mt-0.5 text-tg-text">
                  {describeEvent(event)}
                </div>
              </li>
            ))}
          </ol>

          {issue.can_comment && (
            <div className="mt-4">
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                rows={2}
                maxLength={2000}
                placeholder={tx("Добавить комментарий")}
                className="w-full rounded-tile bg-tg-secondary-bg p-2 text-sm text-tg-text"
              />
              <button
                type="button"
                disabled={commentM.isPending || comment.trim().length === 0}
                onClick={() => commentM.mutate()}
                className="mt-2 min-h-10 w-full rounded-tile bg-tg-secondary-bg text-sm font-medium text-tg-text disabled:opacity-50"
              >{tx("Отправить")}</button>
            </div>
          )}
        </>
      )}
    </BottomSheet>
  );
}

function describeEvent(event: HrIssueDetail["events"][number]): string {
  switch (event.kind) {
    case "created":
      return txIn(currentLocale(), "Завёл карточку");
    case "status":
      return `${txIn(
        currentLocale(),
        ISSUE_STATUS_LABEL[event.from_status ?? "open"],
      )} → ${txIn(
        currentLocale(),
        ISSUE_STATUS_LABEL[event.to_status ?? "open"],
      )}${event.comment ? `: ${event.comment}` : ""}`;
    case "assignee":
      if (!event.comment) return txIn(currentLocale(), "Сменил ответственного");
      if (event.comment === "снят") {
        return txIn(currentLocale(), "Снял ответственного");
      }
      if (event.comment.startsWith("назначен:")) {
        return txIn(currentLocale(), "Назначил ответственного");
      }
      return event.comment;
    case "edited":
      return `${txIn(currentLocale(), "Поправил карточку")}${
        event.comment ? `: ${event.comment}` : ""
      }`;
    case "comment":
      return event.comment ?? "";
    default:
      return event.comment ?? event.kind;
  }
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
        "min-h-10 rounded-tile px-3 text-xs font-medium transition-transform active:scale-[0.98] disabled:opacity-50",
        variant === "primary"
          ? "bg-tg-button text-tg-button-text"
          : "bg-tg-secondary-bg text-tg-text",
      ].join(" ")}
    >
      {children}
    </button>
  );
}
