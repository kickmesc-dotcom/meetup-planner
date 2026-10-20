/**
 * «Требует внимания» — замена наследного блока «алёрты постинга».
 *
 * Тот блок следил за шуточными постами (лох/чухан), которых в продукте больше
 * нет. Управляющему же важно другое: что горит прямо сейчас — просроченные
 * поручения и нерешённые операционные проблемы. Обе ручки уже существуют,
 * поэтому экран ничего не пишет, а только собирает два списка в одно место.
 */
import { useQuery } from "@tanstack/react-query";
import { fetchAdminTasks } from "@/api/hr";
import { fetchIssues, ISSUE_CATEGORY_ICON, ISSUE_STATUS_LABEL } from "@/api/issues";
import { humanizeApiError } from "@/api/client";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
  onOpenTasks?: () => void;
}

function fmtDue(iso: string | null): string {
  if (!iso) return "без срока";
  try {
    return new Date(iso).toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function AttentionScreen({ onBack, onOpenTasks }: Props) {
  const tasks = useQuery({
    queryKey: ["admin", "tasks", "attention"],
    queryFn: () => fetchAdminTasks(),
    staleTime: 30_000,
  });
  const issues = useQuery({
    queryKey: ["issues", "attention"],
    queryFn: () => fetchIssues({ statuses: ["open", "in_progress"], limit: 50 }),
    staleTime: 30_000,
  });

  const overdue = (tasks.data ?? []).filter(
    (t) => t.is_overdue && t.status !== "done" && t.status !== "failed",
  );
  const onReview = (tasks.data ?? []).filter((t) => t.status === "on_review");
  const openIssues = issues.data?.items ?? [];
  const problems = overdue.length + onReview.length + openIssues.length;

  return (
    <SubScreen
      title="🚨 Требует внимания"
      subtitle="Просроченные поручения и открытые проблемы"
      onBack={onBack}
    >
      {tasks.isPending || issues.isPending ? (
        <ListSkeleton rows={4} />
      ) : problems === 0 ? (
        <section className="rounded-xl bg-status-free/10 p-4 text-center">
          <div className="text-2xl mb-1">✓</div>
          <div className="text-sm font-medium text-status-free">Всё под контролем</div>
          <div className="mt-1 text-xs text-tg-hint">
            Просроченных поручений нет, открытых проблем нет.
          </div>
        </section>
      ) : (
        <>
          {tasks.isError && (
            <div className="rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
              ⚠ {humanizeApiError(tasks.error)}
            </div>
          )}
          {issues.isError && (
            <div className="rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
              ⚠ {humanizeApiError(issues.error)}
            </div>
          )}

          {(overdue.length > 0 || onReview.length > 0) && (
            <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-semibold text-tg-text">
                  📝 Поручения
                </div>
                {onOpenTasks && (
                  <button
                    type="button"
                    onClick={onOpenTasks}
                    className="min-h-9 rounded-md bg-tg-bg/70 px-2 text-[11px] text-tg-link active:scale-95 transition-transform"
                  >
                    Открыть →
                  </button>
                )}
              </div>
              {overdue.length > 0 && (
                <div className="text-[11px] text-status-busy">
                  Просрочено: {overdue.length}
                </div>
              )}
              <div className="divide-y divide-tg-bg/40 rounded-lg bg-tg-bg/40">
                {overdue.slice(0, 20).map((t) => (
                  <div key={t.id} className="px-2 py-1.5 space-y-0.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm text-tg-text">{t.title}</span>
                      <span className="shrink-0 text-[10px] tabular-nums text-status-busy">
                        {fmtDue(t.due_at)}
                      </span>
                    </div>
                    <div className="text-[10px] text-tg-hint">
                      {t.assignments.length
                        ? t.assignments.map((a) => a.display_name).join(", ")
                        : `Осталось ${Math.max(0, t.progress_total - t.progress_done)} из ${t.progress_total}`}
                    </div>
                  </div>
                ))}
              </div>
              {onReview.length > 0 && (
                <div className="text-[11px] text-tg-hint">
                  Ждут приёмки: {onReview.length}
                </div>
              )}
            </section>
          )}

          {openIssues.length > 0 && (
            <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-semibold text-tg-text">
                  🛠 Проблемы: {openIssues.length}
                </div>
                {issues.data && issues.data.summary.attention > 0 && (
                  <span className="rounded-full bg-status-busy/15 px-2 py-0.5 text-[10px] text-status-busy">
                    срочных: {issues.data.summary.attention}
                  </span>
                )}
              </div>
              <div className="divide-y divide-tg-bg/40 rounded-lg bg-tg-bg/40">
                {openIssues.slice(0, 20).map((issue) => (
                  <div key={issue.id} className="px-2 py-1.5 space-y-0.5">
                    <div className="flex items-center gap-1.5">
                      <span>{ISSUE_CATEGORY_ICON[issue.category]}</span>
                      <span className="min-w-0 flex-1 truncate text-sm text-tg-text">
                        {issue.title}
                      </span>
                      <span className="shrink-0 text-[10px] text-tg-hint">
                        {ISSUE_STATUS_LABEL[issue.status]}
                      </span>
                    </div>
                    <div className="text-[10px] text-tg-hint">
                      {issue.department_name ?? "без отдела"}
                      {issue.assignee_name ? ` · ${issue.assignee_name}` : ""}
                      {issue.age_hours >= 24
                        ? ` · висит ${Math.floor(issue.age_hours / 24)} дн`
                        : ` · ${Math.round(issue.age_hours)} ч`}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </SubScreen>
  );
}
