import { useQuery } from "@tanstack/react-query";
import {
  fetchDepartmentOverview,
  type DepartmentPerson,
  type DepartmentOverview,
} from "@/api/hr";
import Badge from "@/features/hr/Badge";
import EmployeeCardSheet from "@/features/hr/EmployeeCardSheet";
import { departmentTone, personTone } from "@/features/hr/tone";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import { ListSkeleton } from "@/components/Skeleton";
import { haptic } from "@/tg/webapp";
import { useTx } from "@/i18n";
import { useState } from "react";

/**
 * Дашборд подразделения — что происходит в отделе прямо сейчас.
 *
 * Открывается тапом по плашке подразделения в ленте (или по выбранному
 * отделу в фильтре). Не путать с карточкой коллеги: здесь список людей и их
 * рабочий статус, а подробности (история, медиа, XP) — в карточке по тапу.
 *
 * Правила видимости считает сервер: сотрудник видит свой отдел и без личных
 * отметок времени; руководитель — свои отделы; администратор — все. Экран
 * ничего не досчитывает на клиенте и не показывает то, что не пришло.
 */
export default function DepartmentScreen({
  departmentId,
  onClose,
}: {
  departmentId: number;
  onClose: () => void;
}) {
  const { tx } = useTx();
  const [cardEmployeeId, setCardEmployeeId] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["hr-department", departmentId],
    queryFn: () => fetchDepartmentOverview(departmentId),
    staleTime: 30_000,
  });

  return (
    <div
      className="fixed inset-0 z-40 mx-auto flex w-full max-w-[560px] flex-col bg-tg-bg"
      role="dialog"
      aria-modal="true"
      aria-label={tx("Подразделение")}
    >
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onClose();
          }}
          className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-tg-secondary-bg/60 text-tg-link"
          aria-label={tx("Закрыть подразделение")}
        >
          <Icon name="back" size={20} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-tg-text">
            {q.data
              ? `${q.data.department_emoji ? `${q.data.department_emoji} ` : ""}${q.data.department_name}`
              : tx("Подразделение")}
          </div>
          <div className="truncate text-xs text-tg-hint">
            {q.data
              ? tx("Сотрудников: {count}", { count: q.data.people.length })
              : tx("Кто сегодня в смене")}
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {q.isLoading && <ListSkeleton rows={6} />}
        {q.isError && (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        )}

        {q.data && q.data.people.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Icon name="team" size={34} className="text-tg-hint" />
            <div className="mt-2 text-sm font-medium text-tg-text">
              {tx("В отделе пока никого")}
            </div>
            <div className="mt-1 text-xs text-tg-hint">
              {tx("Сотрудники появятся здесь, когда их добавят в подразделение.")}
            </div>
          </div>
        )}

        {q.data && q.data.people.length > 0 && (
          <div className="space-y-3">
            <Summary view={q.data} />
            <div className="divide-y divide-tg-secondary-bg/70 overflow-hidden rounded-card bg-tg-secondary-bg/40">
              {q.data.people.map((person) => (
                <PersonRow
                  key={person.employee_id}
                  person={person}
                  departmentId={q.data.department_id}
                  showPresence={q.data.show_presence}
                  onOpen={() => {
                    haptic("light");
                    setCardEmployeeId(person.employee_id);
                  }}
                />
              ))}
            </div>
            {!q.data.can_manage && (
              <p className="px-1 text-2xs text-tg-hint">
                {tx(
                  "Ты видишь состав отдела и статус смены. Подробности — в карточке, если коллега открыл профиль.",
                )}
              </p>
            )}
          </div>
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

function Summary({ view }: { view: DepartmentOverview }) {
  const { tx } = useTx();
  return (
    <div className="grid grid-cols-3 gap-2">
      <Stat label={tx("В смене")} value={String(view.on_shift)} />
      <Stat
        label={tx("Сотрудников")}
        value={String(view.people.length)}
        tone="neutral"
      />
      <Stat
        label={tx("Просрочки")}
        value={String(view.overdue)}
        tone={view.overdue > 0 ? "bad" : "neutral"}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "bad";
}) {
  return (
    <div className="rounded-card bg-tg-secondary-bg/60 p-2">
      <div className="text-2xs text-tg-hint">{label}</div>
      <div
        className={[
          "tabular-nums text-lg font-semibold",
          tone === "bad" ? "text-status-busy" : "text-tg-text",
        ].join(" ")}
      >
        {value}
      </div>
    </div>
  );
}

const SHIFT_TITLE: Record<string, string> = {
  planned: "В графике",
  worked: "Смена закрыта",
  sick: "Больничный",
  absent: "Не пришёл",
  dayoff: "Выходной",
  vacation: "Отпуск",
};

function PersonRow({
  person,
  departmentId,
  showPresence,
  onOpen,
}: {
  person: DepartmentPerson;
  departmentId: number;
  showPresence: boolean;
  onOpen: () => void;
}) {
  const { tx } = useTx();
  const personToneValue = personTone(person.employee_id);
  const deptTone = departmentTone(departmentId);
  const checklistDone =
    person.checklist_total > 0 && person.checklist_done >= person.checklist_total;
  const checklistStarted = person.checklist_done > 0 && !checklistDone;

  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-start gap-2 px-3 py-2.5 text-left active:bg-tg-bg/40"
    >
      <span
        className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full text-tg-hint"
        style={{ backgroundColor: personToneValue.soft, border: `1px solid ${personToneValue.border}` }}
        aria-hidden
      >
        <Icon name="profile" size={16} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="truncate text-sm font-medium text-tg-text">
            {person.display_name}
          </span>
          {person.is_self && (
            <span className="rounded-full bg-tg-link/15 px-1.5 text-2xs text-tg-link">
              {tx("ты")}
            </span>
          )}
          {person.is_demo ? (
            <span className="rounded-full bg-tg-bg/70 px-1.5 text-2xs text-tg-hint">
              {tx("тест")}
            </span>
          ) : (
            <Badge
              text={person.badge}
              emoji={person.badge_emoji}
              tone={deptTone}
            />
          )}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-tg-hint">
          {person.shift_status ? (
            <span
              className={[
                "inline-flex items-center gap-1 rounded-full px-1.5",
                person.shift_status === "worked"
                  ? "bg-status-free/15 text-status-free"
                  : person.shift_status === "planned"
                    ? "bg-tg-link/10 text-tg-link"
                    : "bg-tg-bg/60 text-tg-hint",
              ].join(" ")}
            >
              <Icon name="calendar" size={11} />
              {tx(SHIFT_TITLE[person.shift_status] ?? person.shift_status)}
            </span>
          ) : (
            <span>{tx("Вне графика")}</span>
          )}
          {person.checklist_total > 0 && (
            <span
              className={[
                "inline-flex items-center gap-1",
                checklistDone
                  ? "text-status-free"
                  : checklistStarted
                    ? "text-status-busy"
                    : "text-tg-hint",
              ].join(" ")}
            >
              <Icon name="checklist" size={11} />
              {tx("Чек-лист {done}/{total}", {
                done: person.checklist_done,
                total: person.checklist_total,
              })}
            </span>
          )}
          {person.tasks_open > 0 && (
            <span
              className={
                person.tasks_overdue > 0 ? "text-status-busy" : "text-tg-hint"
              }
            >
              {tx("Поручений: {count}", { count: person.tasks_open })}
              {person.tasks_overdue > 0
                ? ` · ${tx("просрочено {count}", { count: person.tasks_overdue })}`
                : ""}
            </span>
          )}
          {showPresence && person.last_seen_at && (
            <span>
              {tx("Вход: {when}", {
                when: relativeWhen(person.last_seen_at, tx),
              })}
            </span>
          )}
        </span>
      </span>
      <Icon name="chevron" size={14} className="mt-2 shrink-0 text-tg-hint" />
    </button>
  );
}

/**
 * «5 минут назад» вместо даты: вопрос дашборда — «кто сейчас у экрана», а не
 * «когда именно». Старше суток показываем дату: «72 часа назад» читать
 * бессмысленно.
 */
function relativeWhen(
  iso: string,
  tx: (text: string, params?: Record<string, string | number>) => string,
): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.max(0, Math.round(diffMs / 60_000));
  if (minutes < 1) return tx("только что");
  if (minutes < 60) return tx("{count} мин назад", { count: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return tx("{count} ч назад", { count: hours });
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}
