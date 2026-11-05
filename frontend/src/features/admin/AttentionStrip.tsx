/**
 * Сводка «что требует внимания» — первым экраном кабинета.
 *
 * Зачем. Все числа уже были на сервере (`/api/admin/dashboard`), но жили в
 * разделе «Требует внимания»: чтобы понять, начинать ли день с разбора,
 * руководитель открывал раздел, возвращался и шёл в «Команду». Пункт плана
 * «сводка первым экраном» — ровно про это, а не про новую аналитику.
 *
 * Почему данные приходят пропсом, а не запрашиваются здесь. Тот же ответ нужен
 * бейджу на карточке раздела; общий ключ react-query склеил бы запросы, но два
 * независимых `isPending` дали бы мигание и два разных «ещё грузится». Один
 * запрос в `AdminScreen` — один источник чисел на всём экране.
 *
 * Почему при ошибке ничего не рисуем. Пустые плитки читались бы как «всё
 * хорошо», хотя мы просто не знаем. Молчание честнее зелёной плашки.
 */
import type { HrDashboard } from "@/api/hr";
import { SkeletonText } from "@/components/Skeleton";
import Icon, { type IconName } from "@/components/Icon";
import { useTx } from "@/i18n";

/** Куда ведёт плитка: разделы кабинета, где лежит разбор. */
export type AttentionTarget = "attention" | "admin-tasks" | "team";

interface Props {
  data: HrDashboard | undefined;
  loading?: boolean;
  onOpen: (target: AttentionTarget) => void;
}

export default function AttentionStrip({ data, loading = false, onOpen }: Props) {
  const { tx } = useTx();

  if (loading) {
    return (
      <section
        data-testid="attention-strip"
        data-state="loading"
        className="rounded-card border border-tg-hint/10 bg-tg-secondary-bg/40 p-3"
      >
        <SkeletonText lines={2} />
      </section>
    );
  }
  // Ошибку сети не превращаем в нули: «0 просрочек» — это утверждение, а не
  // отсутствие ответа.
  if (!data) return null;

  const overdue = data.tasks_overdue;
  const issues = data.open_issues;
  // «Не начали смену» — люди без прогона чек-листа за сегодня. Считаем по
  // `has_run`, а не по `status`: статус ещё зависит от времени закрытия смены
  // и до вечера называет того же человека «в работе».
  const notStarted = data.employees.filter((employee) => !employee.has_run).length;
  // Начали, но не закончили: это не «просрочка» (срок у чек-листа — закрытие
  // смены), но именно то, что руководитель добирает звонком.
  const unfinished = data.employees.filter(
    (employee) =>
      employee.has_run &&
      employee.checklist_total > 0 &&
      employee.checklist_done < employee.checklist_total,
  ).length;

  const nothing = overdue + issues + notStarted + unfinished === 0;

  return (
    <section
      data-testid="attention-strip"
      data-state={nothing ? "clear" : "attention"}
      className={[
        "rounded-card border p-3",
        nothing
          ? "border-status-free/25 bg-status-free/10"
          : "border-status-busy/25 bg-status-busy/5",
      ].join(" ")}
    >
      <header className="flex items-start gap-2">
        <span
          className={[
            "grid h-8 w-8 shrink-0 place-items-center rounded-tile",
            nothing ? "bg-status-free/15 text-status-free" : "bg-status-busy/15 text-status-busy",
          ].join(" ")}
        >
          <Icon name={nothing ? "check" : "alert"} size={17} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-tg-text">
            {nothing ? tx("Всё под контролем") : tx("Требует внимания")}
          </h2>
          <p className="mt-0.5 text-2xs text-tg-hint">
            {tx("Смена: {started} из {total} начали", {
              started: data.shifts_started,
              total: data.total_employees,
            })}
          </p>
        </div>
      </header>

      {nothing ? (
        <p className="mt-2 text-xs text-tg-hint">
          {tx("Просроченных поручений нет, открытых проблем нет.")}
        </p>
      ) : (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Tile
            testId="attention-overdue"
            icon="tasks"
            value={overdue}
            label={tx("Просрочено")}
            tone={overdue > 0 ? "alert" : "muted"}
            onClick={() => onOpen("admin-tasks")}
          />
          <Tile
            testId="attention-issues"
            icon="alert"
            value={issues}
            label={tx("Проблемы")}
            tone={issues > 0 ? "alert" : "muted"}
            onClick={() => onOpen("attention")}
          />
          <Tile
            testId="attention-not-started"
            icon="team"
            value={notStarted}
            label={tx("Не начали смену")}
            tone={notStarted > 0 ? "alert" : "muted"}
            onClick={() => onOpen("team")}
          />
          <Tile
            testId="attention-unfinished"
            icon="clipboard"
            value={unfinished}
            label={tx("Не закрыли чек-лист")}
            tone={unfinished > 0 ? "warn" : "muted"}
            onClick={() => onOpen("team")}
          />
        </div>
      )}
    </section>
  );
}

function Tile({
  testId,
  icon,
  value,
  label,
  tone,
  onClick,
}: {
  testId: string;
  icon: IconName;
  value: number;
  label: string;
  tone: "alert" | "warn" | "muted";
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      className="press flex min-h-11 items-center gap-2 rounded-tile bg-tg-bg/60 px-2.5 py-2 text-left hover:bg-tg-bg/80"
    >
      <Icon
        name={icon}
        size={15}
        className={
          tone === "alert"
            ? "text-status-busy"
            : tone === "warn"
              ? "text-tg-hint"
              : "text-tg-hint"
        }
      />
      <span
        className={[
          "text-lg font-semibold leading-none tabular-nums",
          tone === "alert" ? "text-status-busy" : "text-tg-text",
        ].join(" ")}
      >
        {value}
      </span>
      <span className="min-w-0 flex-1 text-2xs text-tg-hint">{label}</span>
    </button>
  );
}
