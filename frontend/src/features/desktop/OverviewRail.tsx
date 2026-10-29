import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { countOpenTasks, fetchChecklist, fetchTasks } from "@/api/hr";
import { fetchIssues } from "@/api/issues";
import Icon, { type IconName } from "@/components/Icon";
import ProgressBar from "@/components/ProgressBar";
import { SkeletonText } from "@/components/Skeleton";
import { useUI, type Tab } from "@/store/ui";
import { haptic } from "@/tg/webapp";
import { useTx } from "@/i18n";
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
  const { tx } = useTx();
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
      aria-label={tx("Сводка смены")}
      data-testid="overview-rail"
      className="hidden w-[320px] shrink-0 overflow-y-auto border-l border-tg-hint/10 px-4 py-4 lg:block"
    >
      <h2 className="text-2xs font-semibold uppercase tracking-wide text-tg-hint">
        {tx("Сводка смены")}
      </h2>

      <Card
        icon="clipboard"
        title={tx("Чек-лист")}
        action={
          <RailLink onClick={() => go("checklist")}>
            {shift && shift.total > 0 ? tx("Открыть") : tx("Начать")}
          </RailLink>
        }
      >
        {checklistQ.isLoading ? (
          // Каркас вместо "Загружаем…": рельс уже нарисован, грузится только
          // содержимое карточки, и его форма известна заранее.
          <SkeletonText lines={2} />
        ) : shift && shift.total > 0 ? (
          <ProgressBar
            value={shift.done}
            total={shift.total}
            label={
              shift.status === "done"
                ? tx("Смена закрыта")
                : tx("Выполнено")
            }
            tone={shift.status === "done" ? "muted" : "brand"}
          />
        ) : (
          <Muted>{tx("Пунктов на сегодня нет")}</Muted>
        )}
      </Card>

      <Card
        icon="tasks"
        title={tx("Поручения")}
        action={
          <RailLink onClick={() => go("tasks")}>{tx("Мои задачи")}</RailLink>
        }
      >
        {tasksQ.isLoading ? (
          <SkeletonText lines={2} />
        ) : tasksQ.isError ? (
          <Muted>{tx("Не удалось загрузить")}</Muted>
        ) : (
          <div className="flex items-end gap-4">
            <Figure value={openCount} caption={tx("открыто")} />
            <Figure
              value={overdue}
              caption={tx("просрочено")}
              tone={overdue > 0 ? "alert" : "muted"}
            />
          </div>
        )}
      </Card>

      <Card
        icon="alert"
        title={tx("Проблемы")}
        action={<RailLink onClick={() => go("issues")}>{tx("Журнал")}</RailLink>}
      >
        {issuesQ.isLoading ? (
          <SkeletonText lines={2} />
        ) : problems ? (
          <div className="flex items-end gap-4">
            <Figure value={problems.total_open ?? 0} caption={tx("открыто")} />
            <Figure
              value={problems.attention ?? 0}
              caption={tx("требуют внимания")}
              tone={(problems.attention ?? 0) > 0 ? "alert" : "muted"}
            />
          </div>
        ) : (
          <Muted>{tx("Нет данных")}</Muted>
        )}
      </Card>

      <h2 className="mt-5 text-2xs font-semibold uppercase tracking-wide text-tg-hint">
        {tx("Быстрый переход")}
      </h2>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <Quick tab="shifts" icon="calendar" label={tx("График")} onClick={go} />
        <Quick tab="materials" icon="book" label={tx("Материалы")} onClick={go} />
        <Quick tab="team" icon="team" label={tx("Команда")} onClick={go} />
        {/* Вместо старого «Календаря» — встречи: расписание смен уже выше. */}
        <Quick tab="meetings" icon="clock" label={tx("Встречи")} onClick={go} />
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
      className="lift flex min-h-11 items-center gap-2 rounded-tile border border-tg-hint/10 bg-tg-secondary-bg/30 px-2.5 text-left text-xs text-tg-text hover:bg-tg-secondary-bg/70"
    >
      <Icon name={icon} size={15} />
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </button>
  );
}
