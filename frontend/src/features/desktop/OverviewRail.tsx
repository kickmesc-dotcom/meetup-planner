import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { countOpenTasks, fetchChecklist, fetchTasks } from "@/api/hr";
import { fetchIssues } from "@/api/issues";
import Icon, { type IconName } from "@/components/Icon";
import ProgressBar from "@/components/ProgressBar";
import { useUI, type Tab } from "@/store/ui";
import { haptic } from "@/tg/webapp";

/**
 * Правый рельс сводки на широком экране.
 *
 * Зачем: на мобильном главный экран — это лента, а «что у меня сейчас» живёт в
 * соседней вкладке. На ПК места хватает, чтобы показать это рядом, как в
 * обычной админ-панели: прогресс смены, поручения, проблемы и быстрые переходы.
 *
 * Данных новых нет: запросы те же (`hr-checklist`, `hr-tasks`, `hr-issues`), с
 * теми же ключами, что у «Моих задач» и чек-листа, поэтому переход по кнопке
 * открывает уже загруженный экран без повторного запроса.
 */
export default function OverviewRail() {
  const setTab = useUI((s) => s.setTab);

  const checklistQ = useQuery({
    queryKey: ["hr-checklist"],
    queryFn: () => fetchChecklist(),
    staleTime: 30_000,
  });
  const tasksQ = useQuery({
    queryKey: ["hr-tasks", false],
    queryFn: () => fetchTasks(false),
  });
  const issuesQ = useQuery({
    queryKey: ["hr-issues", "panel"],
    queryFn: () => fetchIssues({ statuses: ["open", "in_progress"], limit: 1 }),
    staleTime: 60_000,
  });

  const shift = checklistQ.data;
  const tasks = tasksQ.data ?? [];
  // Тот же счёт, что в «Моих задачах» и на бейдже вкладки: правило живёт в
  // `countOpenTasks`, поэтому числа не разъезжаются между экранами.
  const { open: openCount, overdue } = countOpenTasks(tasks);
  const problems = issuesQ.data?.summary;

  const go = (tab: Tab) => {
    haptic("selection");
    setTab(tab);
  };

  return (
    <aside
      aria-label="Сводка смены"
      data-testid="overview-rail"
      className="hidden w-[320px] shrink-0 overflow-y-auto border-l border-tg-hint/10 px-4 py-4 lg:block"
    >
      <h2 className="text-2xs font-semibold uppercase tracking-wide text-tg-hint">
        Сводка смены
      </h2>

      <Card
        icon="clipboard"
        title="Чек-лист"
        action={
          <RailLink onClick={() => go("checklist")}>
            {shift && shift.total > 0 ? "Открыть" : "Начать"}
          </RailLink>
        }
      >
        {checklistQ.isLoading ? (
          <Muted>Загружаем…</Muted>
        ) : shift && shift.total > 0 ? (
          <ProgressBar
            value={shift.done}
            total={shift.total}
            label={shift.status === "done" ? "Смена закрыта" : "Выполнено"}
            tone={shift.status === "done" ? "muted" : "brand"}
          />
        ) : (
          <Muted>Пунктов на сегодня нет</Muted>
        )}
      </Card>

      <Card
        icon="tasks"
        title="Поручения"
        action={<RailLink onClick={() => go("tasks")}>Мои задачи</RailLink>}
      >
        {tasksQ.isLoading ? (
          <Muted>Загружаем…</Muted>
        ) : tasksQ.isError ? (
          <Muted>Не удалось загрузить</Muted>
        ) : (
          <div className="flex items-end gap-4">
            <Figure value={openCount} caption="открыто" />
            <Figure
              value={overdue}
              caption="просрочено"
              tone={overdue > 0 ? "alert" : "muted"}
            />
          </div>
        )}
      </Card>

      <Card
        icon="alert"
        title="Проблемы"
        action={<RailLink onClick={() => go("issues")}>Журнал</RailLink>}
      >
        {issuesQ.isLoading ? (
          <Muted>Загружаем…</Muted>
        ) : problems ? (
          <div className="flex items-end gap-4">
            <Figure value={problems.total_open ?? 0} caption="открыто" />
            <Figure
              value={problems.attention ?? 0}
              caption="требуют внимания"
              tone={(problems.attention ?? 0) > 0 ? "alert" : "muted"}
            />
          </div>
        ) : (
          <Muted>Нет данных</Muted>
        )}
      </Card>

      <h2 className="mt-5 text-2xs font-semibold uppercase tracking-wide text-tg-hint">
        Быстрый переход
      </h2>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <Quick tab="shifts" icon="calendar" label="Табель" onClick={go} />
        <Quick tab="materials" icon="book" label="Материалы" onClick={go} />
        <Quick tab="team" icon="team" label="Команда" onClick={go} />
        <Quick tab="calendar" icon="clock" label="Календарь" onClick={go} />
      </div>
    </aside>
  );
}

function Card({
  icon,
  title,
  action,
  children,
}: {
  icon: IconName;
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="mt-2 rounded-card border border-tg-hint/10 bg-tg-secondary-bg/30 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-tile bg-tg-bg/70 text-tg-hint">
          <Icon name={icon} size={15} />
        </span>
        <h3 className="min-w-0 flex-1 truncate text-xs font-semibold text-tg-text">
          {title}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function RailLink({
  onClick,
  children,
}: {
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="shrink-0 rounded-full px-2 py-1 text-2xs font-medium text-tg-link hover:bg-tg-link/10"
    >
      {children}
    </button>
  );
}

function Figure({
  value,
  caption,
  tone = "muted",
}: {
  value: number;
  caption: string;
  tone?: "muted" | "alert";
}) {
  return (
    <div>
      <div
        className={[
          "text-2xl font-semibold leading-none tabular-nums",
          tone === "alert" ? "text-status-busy" : "text-tg-text",
        ].join(" ")}
      >
        {value}
      </div>
      <div className="mt-1 text-2xs text-tg-hint">{caption}</div>
    </div>
  );
}

function Muted({ children }: { children: ReactNode }) {
  return <p className="text-xs text-tg-hint">{children}</p>;
}

function Quick({
  tab,
  icon,
  label,
  onClick,
}: {
  tab: Tab;
  icon: IconName;
  label: string;
  onClick: (tab: Tab) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onClick(tab)}
      className="flex min-h-11 items-center gap-2 rounded-tile border border-tg-hint/10 bg-tg-secondary-bg/30 px-2.5 text-left text-xs text-tg-text hover:bg-tg-secondary-bg/70"
    >
      <Icon name={icon} size={15} />
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </button>
  );
}
