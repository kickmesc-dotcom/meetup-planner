import { useQuery } from "@tanstack/react-query";
import { fetchWeekSummary, type HrWeekBlocker } from "@/api/hr";
import { ISSUE_CATEGORY_ICON, ISSUE_CATEGORY_LABEL, type IssueCategory } from "@/api/issues";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import { CardSkeleton } from "@/components/Skeleton";
import { currentIntlLocale, useTx } from "@/i18n";

/**
 * «Что мешало смене» — недельная сводка руководителю.
 *
 * Дневной отчёт отвечает «как прошла смена». Здесь другой вопрос: что
 * повторяется. Одна сломанная посудомойка — случайность, три за неделю —
 * причина. Поэтому сначала числа, потом категории, потом конкретные карточки:
 * сверху вниз — от «что делать» к «где смотреть».
 *
 * Период фиксирован (последние семь дней): сводка, которую можно сдвинуть,
 * перестаёт сравниваться с прошлой неделей.
 */
export default function WeekSummaryScreen({
  onBack,
  departmentId = null,
}: {
  onBack: () => void;
  departmentId?: number | null;
}) {
  const { tx } = useTx();
  const q = useQuery({
    queryKey: ["week-summary", departmentId],
    queryFn: () => fetchWeekSummary(departmentId),
  });

  const data = q.data;
  const fmt = (iso: string) => {
    const d = new Date(`${iso}T00:00:00`);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(currentIntlLocale(), {
      day: "2-digit",
      month: "long",
    });
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <button
          type="button"
          onClick={onBack}
          className="min-h-11 min-w-11 rounded-tile text-lg text-tg-link"
          aria-label={tx("Назад к отчёту")}
        >
          <Icon name="back" size={18} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-sm font-semibold text-tg-text">
            <Icon name="alert" size={15} />
            {tx("Что мешало смене")}
          </div>
          <div className="text-xs text-tg-hint">
            {data ? `${fmt(data.start)} — ${fmt(data.end)}` : tx("Последние 7 дней")}
          </div>
        </div>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {q.isError && (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        )}
        {q.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {data && (
          <>
            <section className="grid grid-cols-2 gap-2">
              <Metric label={tx("Новые проблемы")} value={data.issues_new} />
              <Metric label={tx("Закрыто")} value={data.issues_closed} tone="free" />
              <Metric
                label={tx("Открыто сейчас")}
                value={data.issues_open}
                tone={data.issues_open > 0 ? "busy" : undefined}
              />
              <Metric
                label={tx("Просрочено поручений")}
                value={data.tasks_overdue_open}
                tone={data.tasks_overdue_open > 0 ? "busy" : undefined}
              />
            </section>

            <p className="text-xs text-tg-hint">
              {tx("Сделано поручений: {done}, из них с опозданием — {late}.", {
                done: data.tasks_done,
                late: data.tasks_done_late,
              })}
            </p>

            {data.categories.length > 0 && (
              <section className="space-y-1.5">
                <h2 className="text-heading text-tg-text">
                  {tx("Чаще всего мешало")}
                </h2>
                <div className="space-y-1">
                  {data.categories.map((row) => (
                    <div
                      key={row.category}
                      className="flex items-center gap-2 rounded-tile bg-tg-secondary-bg/60 px-2.5 py-1.5 text-xs text-tg-text"
                    >
                      <span aria-hidden="true">
                        {ISSUE_CATEGORY_ICON[row.category as IssueCategory] ?? "🛠"}
                      </span>
                      <span className="min-w-0 flex-1 truncate">
                        {tx(
                          ISSUE_CATEGORY_LABEL[row.category as IssueCategory] ?? "Другое",
                        )}
                      </span>
                      <span className="font-medium">{row.count}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <section className="space-y-1.5">
              <h2 className="text-heading text-tg-text">{tx("Проблемы за неделю")}</h2>
              {data.blockers.length === 0 ? (
                <p className="rounded-card bg-tg-secondary-bg/40 p-3 text-center text-xs text-tg-hint">
                  {tx("За неделю проблем не заводили — хороший знак.")}
                </p>
              ) : (
                <div className="divide-y divide-tg-secondary-bg/70 overflow-hidden rounded-card bg-tg-secondary-bg/30">
                  {data.blockers.map((item) => (
                    <BlockerRow key={item.issue_id} item={item} />
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function BlockerRow({ item }: { item: HrWeekBlocker }) {
  const { tx } = useTx();
  const age =
    item.age_hours >= 48
      ? tx("{days} дн", { days: Math.floor(item.age_hours / 24) })
      : tx("{hours} ч", { hours: item.age_hours });
  return (
    <div className="flex items-start gap-2 px-3 py-2">
      <span aria-hidden="true" className="mt-0.5">
        {ISSUE_CATEGORY_ICON[item.category as IssueCategory] ?? "🛠"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-xs text-tg-text">{item.title}</div>
        <div className="mt-0.5 text-2xs text-tg-hint">
          {tx(ISSUE_CATEGORY_LABEL[item.category as IssueCategory] ?? "Другое")}
          {" · "}
          {item.resolved_at ? tx("закрыта") : tx("висит {age}", { age })}
        </div>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "busy" | "free";
}) {
  return (
    <div className="rounded-card bg-tg-secondary-bg/60 p-2.5">
      <div
        className={[
          "text-title",
          tone === "busy"
            ? "text-status-busy"
            : tone === "free"
              ? "text-status-free"
              : "text-tg-text",
        ].join(" ")}
      >
        {value}
      </div>
      <div className="mt-0.5 text-2xs text-tg-hint">{label}</div>
    </div>
  );
}
