import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  downloadShiftCsv,
  fetchDepartments,
  fetchEmployee,
  fetchShiftReport,
  type HrDepartmentRow,
  type HrShiftReport,
  type HrStandardCoverage,
} from "@/api/hr";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import { InlineIcon } from "@/components/Icon";
import { useUI } from "@/store/ui";
import { useTx, type Locale } from "@/i18n";

/**
 * Отчёт смены.
 *
 * Кабинет управляющего отвечает «что горит сейчас». Здесь — срез на дату:
 * смены, поручения по статусам, проблемы и главное — обязательные стандарты,
 * которые сдал не каждый. Дата и отдел выбираются сверху; сервер сам сужает
 * срез до отдела руководителя, поэтому подмена отдела в запросе ничего не
 * откроет.
 *
 * Перевод (24.10.2026): подписи идут через `tx(...)`. Названия отделов и
 * стандартов, имена людей остаются как есть — это данные управляющего, а не
 * интерфейс. Дата форматируется по локали (`Intl`), а не по-русски всегда.
 */

function todayIso(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function fmtDate(iso: string, locale: Locale): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(locale === "en" ? "en-GB" : "ru-RU", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
}

export default function ReportsScreen() {
  const { tx, locale } = useTx();
  const setTab = useUI((s) => s.setTab);
  const [on, setOn] = useState<string>(todayIso());
  const [departmentId, setDepartmentId] = useState<number | null>(null);
  const [onlyGaps, setOnlyGaps] = useState(true);

  const meQ = useQuery({ queryKey: ["hr-me"], queryFn: fetchEmployee });
  const departmentsQ = useQuery({
    queryKey: ["hr-departments"],
    queryFn: fetchDepartments,
    enabled: !!meQ.data?.is_staff,
  });
  const reportQ = useQuery({
    queryKey: ["hr-shift-report", on, departmentId],
    queryFn: () => fetchShiftReport({ on, department_id: departmentId }),
  });

  const report = reportQ.data;
  const requiredStandards = (report?.standards ?? []).filter(
    (standard) => standard.required,
  );
  // «Только пробелы» = обязательные, которые сдал не каждый. Снятая галочка
  // показывает всю базу — так видно и справочные стандарты без пробела.
  const standards = (report?.standards ?? []).filter(
    (standard) =>
      !onlyGaps || (standard.required && standard.passed < standard.total),
  );

  const download = async () => {
    try {
      haptic("light");
      const name = await downloadShiftCsv({ on, department_id: departmentId });
      await showAlert(tx("Файл готов: {name}", { name }));
    } catch {
      await showAlert(tx("Не получилось скачать файл — попробуй ещё раз."));
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            setTab("profile");
          }}
          className="min-h-11 min-w-11 rounded-tile text-lg text-tg-link"
          aria-label={tx("Назад в профиль")}
        >
          ‹
        </button>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-tg-text">
            {tx("Отчёт смены")}
          </div>
          <div className="text-xs text-tg-hint">
            {report ? fmtDate(report.work_date, locale) : tx("Срез на дату")}
          </div>
        </div>
        <button
          type="button"
          onClick={() => void download()}
          className="min-h-9 rounded-tile bg-tg-secondary-bg px-3 text-xs font-medium text-tg-text"
        >
          CSV
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        <section className="rounded-card bg-tg-secondary-bg/60 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              value={on}
              max={todayIso()}
              onChange={(event) => setOn(event.target.value || todayIso())}
              className="min-h-9 rounded-tile border border-tg-secondary-bg bg-tg-bg px-2 text-xs text-tg-text"
              aria-label={tx("Дата смены")}
            />
            {!!meQ.data?.is_staff && (
              <select
                value={departmentId ?? ""}
                onChange={(event) =>
                  setDepartmentId(event.target.value ? Number(event.target.value) : null)
                }
                className="min-h-9 rounded-tile border border-tg-secondary-bg bg-tg-bg px-2 text-xs text-tg-text"
                aria-label={tx("Подразделение")}
              >
                <option value="">{tx("Все отделы")}</option>
                {(departmentsQ.data ?? []).map((dept) => (
                  <option key={dept.id} value={dept.id}>
                    {dept.emoji ? `${dept.emoji} ` : ""}
                    {dept.name}
                  </option>
                ))}
              </select>
            )}
          </div>
          {report && (
            <div className="mt-2 text-xs text-tg-hint">
              {report.scope === "all"
                ? tx("Видно все отделы")
                : tx("Видно своё подразделение")}{" "}
              · {tx("людей {count}", { count: report.employees_total })}
            </div>
          )}
        </section>

        {reportQ.isError && (
          <ErrorState error={reportQ.error} onRetry={() => void reportQ.refetch()} />
        )}

        {reportQ.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {report && (
          <>
            <section className="grid grid-cols-2 gap-2">
              <Metric
                label={tx("Смен начато")}
                value={report.shifts_started}
                hint={tx("из {count}", { count: report.employees_total })}
              />
              <Metric
                label={tx("Смен закрыто")}
                value={report.shifts_done}
                hint={tx("чек-лист на 100%")}
              />
              <Metric
                label={tx("Поручений")}
                value={report.tasks_shift}
                hint={tx("выполнено {count}", { count: report.tasks_done })}
              />
              <Metric
                label={tx("На проверке")}
                value={report.tasks_on_review}
                hint={tx("сдано, но не принято")}
                accent={report.tasks_on_review > 0}
              />
              <Metric
                label={tx("Просрочено")}
                value={report.tasks_overdue}
                hint={tx("за эту смену")}
                accent={report.tasks_overdue > 0}
              />
              <Metric
                label={tx("Пробелы стандартов")}
                value={report.required_gaps}
                hint={tx("обязательные не сданы")}
                accent={report.required_gaps > 0}
              />
            </section>

            <section className="rounded-card bg-tg-secondary-bg/60 p-3">
              <div className="flex items-baseline justify-between">
                <h2 className="text-sm font-semibold text-tg-text">
                  {tx("Сейчас в работе")}
                </h2>
                <span className="text-xs text-tg-hint">
                  {tx("{tasks} поручений · {issues} проблем", {
                    tasks: report.tasks_open,
                    issues: report.issues_open,
                  })}
                </span>
              </div>
              <div className="mt-1 text-xs text-tg-hint">
                {tx("Новых проблем за смену: {count}", {
                  count: report.issues_new,
                })}
              </div>
            </section>

            {report.departments.length > 1 && (
              <section className="space-y-2">
                <h2 className="px-1 text-sm font-semibold text-tg-text">
                  {tx("По отделам")}
                </h2>
                {report.departments.map((dept) => (
                  <DepartmentCard key={dept.department_id} dept={dept} />
                ))}
              </section>
            )}

            <section className="space-y-2">
              <div className="flex items-center justify-between px-1">
                <h2 className="text-sm font-semibold text-tg-text">
                  {tx("Обязательные стандарты")}
                </h2>
                <label className="flex items-center gap-1 text-xs text-tg-hint">
                  <input
                    type="checkbox"
                    checked={onlyGaps}
                    onChange={(event) => setOnlyGaps(event.target.checked)}
                  />
                  {tx("только пробелы")}
                </label>
              </div>
              {standards.length === 0 ? (
                <div className="rounded-card bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
                  {requiredStandards.length === 0 ? (
                    tx(
                      "Обязательных стандартов пока нет — отметь их в базе стандартов.",
                    )
                  ) : (
                    <>
                      <InlineIcon name="check" />
                      {tx("Все обязательные стандарты сданы.")}
                    </>
                  )}
                </div>
              ) : (
                standards.map((standard) => (
                  <StandardCard key={standard.standard_id} standard={standard} />
                ))
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  accent = false,
}: {
  label: string;
  value: number;
  hint?: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-card bg-tg-secondary-bg/60 p-3">
      <div className="text-xs text-tg-hint">{label}</div>
      <div
        className={[
          "mt-0.5 text-xl font-semibold tabular-nums",
          accent ? "text-status-busy" : "text-tg-text",
        ].join(" ")}
      >
        {value}
      </div>
      {hint && <div className="text-2xs text-tg-hint">{hint}</div>}
    </div>
  );
}

function DepartmentCard({ dept }: { dept: HrDepartmentRow }) {
  const { tx } = useTx();
  return (
    <div className="rounded-card bg-tg-secondary-bg/60 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0 truncate text-sm font-medium text-tg-text">
          {dept.emoji ? `${dept.emoji} ` : ""}
          {dept.name}
        </div>
        <div className="shrink-0 text-xs text-tg-hint">
          {tx("{count} чел.", { count: dept.employees })}
        </div>
      </div>
      <div className="mt-1 text-xs text-tg-hint">
        {tx("Смены {started}/{employees} · закрыто {done}", {
          started: dept.shifts_started,
          employees: dept.employees,
          done: dept.shifts_done,
        })}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-tg-hint">
        <span>{tx("поручений {count}", { count: dept.tasks_shift })}</span>
        <span>{tx("на проверке {count}", { count: dept.tasks_on_review })}</span>
        <span className={dept.tasks_overdue > 0 ? "text-status-busy" : ""}>
          {tx("просрочено {count}", { count: dept.tasks_overdue })}
        </span>
        <span className={dept.issues_open > 0 ? "text-status-busy" : ""}>
          {tx("проблем {count}", { count: dept.issues_open })}
        </span>
        <span className={dept.required_gaps > 0 ? "text-status-busy" : ""}>
          {tx("пробелов {count}", { count: dept.required_gaps })}
        </span>
      </div>
    </div>
  );
}

function StandardCard({ standard }: { standard: HrStandardCoverage }) {
  const { tx } = useTx();
  const percent =
    standard.total > 0 ? Math.round((standard.passed * 100) / standard.total) : 0;
  return (
    <div className="rounded-card bg-tg-secondary-bg/60 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0 text-sm font-medium text-tg-text">
          {standard.emoji ? `${standard.emoji} ` : ""}
          {standard.title}
          {standard.required && (
            <span className="ml-1 rounded-tile bg-status-busy/15 px-1 text-2xs text-status-busy">
              {tx("обязательный")}
            </span>
          )}
        </div>
        <div className="shrink-0 text-xs tabular-nums text-tg-hint">
          {standard.passed}/{standard.total} · {percent}%
        </div>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-tg-bg">
        <div
          className={percent === 100 ? "h-full bg-status-online" : "h-full bg-status-busy"}
          style={{ width: `${percent}%` }}
        />
      </div>
      {standard.missing.length > 0 && (
        <div className="mt-1.5 text-xs text-tg-hint">
          {tx("Не сдали: {names}", {
            names: standard.missing.map((person) => person.display_name).join(", "),
          })}
        </div>
      )}
      {standard.department_name && (
        <div className="mt-0.5 text-2xs text-tg-hint">
          {tx("Только {name}", { name: standard.department_name })}
        </div>
      )}
    </div>
  );
}

/** Для тестов и повторного использования: без `report` экран не падает. */
export type { HrShiftReport };
