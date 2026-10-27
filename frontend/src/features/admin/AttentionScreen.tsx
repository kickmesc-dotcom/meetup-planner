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
import Icon, { InlineIcon } from "@/components/Icon";
import SubScreen from "./SubScreen";

import { currentIntlLocale, currentLocale, tx as tr, useTx } from "@/i18n";
interface Props {
  onBack: () => void;
  onOpenTasks?: () => void;
}

function fmtDue(iso: string | null): string {
  if (!iso) return tr(currentLocale(), "без срока");
  try {
    return new Date(iso).toLocaleString(currentIntlLocale(), {
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
  const { tx } = useTx();
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
      title={tx("Требует внимания")}
      subtitle={tx("Просроченные поручения и открытые проблемы")}
      onBack={onBack}
    >
      {tasks.isPending || issues.isPending ? (
        <ListSkeleton rows={4} />
      ) : problems === 0 ? (
        <section className="rounded-card bg-status-free/10 p-4 text-center">
          <Icon name="check" size={28} className="mx-auto mb-1 text-status-free" />
          <div className="text-sm font-medium text-status-free">
            {tx("Всё под контролем")}
          </div>
          <div className="mt-1 text-xs text-tg-hint">
            {tx("Просроченных поручений нет, открытых проблем нет.")}
          </div>
        </section>
      ) : (
        <>
          {tasks.isError && (
            <div className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
              <InlineIcon name="alert" />
              {humanizeApiError(tasks.error)}
            </div>
          )}
          {issues.isError && (
            <div className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
              <InlineIcon name="alert" />
              {humanizeApiError(issues.error)}
            </div>
          )}

          {(overdue.length > 0 || onReview.length > 0) && (
            <section className="rounded-card bg-tg-secondary-bg/60 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-semibold text-tg-text">
                  {tx("Поручения")}
                </div>
                {onOpenTasks && (
                  <button
                    type="button"
                    onClick={onOpenTasks}
                    className="min-h-9 rounded-tile bg-tg-bg/70 px-2 text-xs text-tg-link press"
                  >
                    {tx("Открыть →")}
                  </button>
                )}
              </div>
              {overdue.length > 0 && (
                <div className="text-xs text-status-busy">
                  {tx("Просрочено: {count}", { count: overdue.length })}
                </div>
              )}
              <div className="divide-y divide-tg-bg/40 rounded-tile bg-tg-bg/40">
                {overdue.slice(0, 20).map((t) => (
                  <div key={t.id} className="px-2 py-1.5 space-y-0.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm text-tg-text">{t.title}</span>
                      <span className="shrink-0 text-2xs tabular-nums text-status-busy">
                        {fmtDue(t.due_at)}
                      </span>
                    </div>
                    <div className="text-2xs text-tg-hint">
                      {t.assignments.length
                        ? t.assignments.map((a) => a.display_name).join(", ")
                        : tx("Осталось {left} из {total}", {
                            left: Math.max(0, t.progress_total - t.progress_done),
                            total: t.progress_total,
                          })}
                    </div>
                  </div>
                ))}
              </div>
              {onReview.length > 0 && (
                <div className="text-xs text-tg-hint">
                  {tx("Ждут приёмки: {count}", { count: onReview.length })}
                </div>
              )}
            </section>
          )}

          {openIssues.length > 0 && (
            <section className="rounded-card bg-tg-secondary-bg/60 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-semibold text-tg-text">
                  {tx("Проблемы: {count}", { count: openIssues.length })}
                </div>
                {issues.data && issues.data.summary.attention > 0 && (
                  <span className="rounded-full bg-status-busy/15 px-2 py-0.5 text-2xs text-status-busy">
                    {tx("срочных: {count}", {
                      count: issues.data.summary.attention,
                    })}
                  </span>
                )}
              </div>
              <div className="divide-y divide-tg-bg/40 rounded-tile bg-tg-bg/40">
                {openIssues.slice(0, 20).map((issue) => (
                  <div key={issue.id} className="px-2 py-1.5 space-y-0.5">
                    <div className="flex items-center gap-1.5">
                      <span>{ISSUE_CATEGORY_ICON[issue.category]}</span>
                      <span className="min-w-0 flex-1 truncate text-sm text-tg-text">
                        {issue.title}
                      </span>
                      <span className="shrink-0 text-2xs text-tg-hint">
                        {ISSUE_STATUS_LABEL[issue.status]}
                      </span>
                    </div>
                    <div className="text-2xs text-tg-hint">
                      {issue.department_name ?? tx("без отдела")}
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
