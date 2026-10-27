import { useQuery } from "@tanstack/react-query";
import { fetchDigest } from "@/api/hr";
import ErrorState from "@/components/ErrorState";
import Icon, { type IconName } from "@/components/Icon";
import { SkeletonText } from "@/components/Skeleton";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";
import { useTx } from "@/i18n";

/**
 * «Сводка дня» — экран утреннего сообщения (план, 8.2).
 *
 * Зачем экран, если то же приходит в Telegram. Сообщение живёт в чате и тонет
 * к обеду; здесь руководитель открывает его в любой момент и — главное — видит
 * не только числа, но и **что за ними делать**: каждое число рядом с кнопкой
 * перехода. Поэтому экран не старается быть красивее сообщения, он старается
 * быть его продолжением.
 *
 * Правило загрузки общее (план, раздел 9): заголовок и объяснение — в первом
 * кадре, числа занимают заранее нарисованные плитки.
 */
export default function DigestScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const digestQ = useQuery({ queryKey: ["hr-digest"], queryFn: fetchDigest });
  const setTab = useUI((s) => s.setTab);

  const go = (tab: "tasks" | "issues" | "checklist") => {
    haptic("light");
    setTab(tab);
  };

  const digest = digestQ.data;

  return (
    <div className="flex h-full flex-col bg-tg-bg">
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onBack();
          }}
          className="min-h-11 min-w-11 rounded-tile text-lg text-tg-link"
          aria-label={tx("Назад")}
        >
          ‹
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-sm font-semibold text-tg-text">
            <Icon name="calendar" size={16} />
            {tx("Сводка дня")}
          </div>
          <div className="text-xs text-tg-hint">
            {tx("То же, что приходит в 08:30 — без поиска по чату")}
          </div>
        </div>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {digestQ.isError && (
          <ErrorState error={digestQ.error} onRetry={() => void digestQ.refetch()} />
        )}

        {digestQ.isPending && (
          <>
            <div className="grid grid-cols-2 gap-2" data-testid="digest-skeleton">
              <SkeletonTile />
              <SkeletonTile />
              <SkeletonTile />
              <SkeletonTile />
            </div>
            <div className="rounded-card bg-tg-secondary-bg/60 p-3">
              <SkeletonText lines={3} />
            </div>
          </>
        )}

        {digest && (
          <>
            {digest.calm && (
              <section className="rounded-card bg-status-free/10 p-3">
                <h2 className="flex items-center gap-1.5 text-sm font-semibold text-tg-text">
                  <Icon name="check" size={15} className="text-status-free" />
                  {tx("Всё спокойно")}
                </h2>
                <p className="mt-1 text-xs text-tg-hint">
                  {tx("Просрочек и срочных проблем нет — можно заниматься сменой.")}
                </p>
              </section>
            )}

            <section className="grid grid-cols-2 gap-2">
              <Tile
                icon="clock"
                label={tx("Просрочено")}
                value={digest.overdue_tasks}
                danger={digest.overdue_tasks > 0}
                onOpen={() => go("tasks")}
              />
              <Tile
                icon="checklist"
                label={tx("Не открыли чек-лист")}
                value={digest.not_started}
                hint={
                  digest.planned_today > 0
                    ? tx("из {count} смен", { count: digest.planned_today })
                    : undefined
                }
                danger={digest.not_started > 0}
                onOpen={() => go("checklist")}
              />
              <Tile
                icon="alert"
                label={tx("Проблемы")}
                value={digest.problems_open}
                hint={
                  digest.problems_attention > 0
                    ? tx("срочных: {count}", { count: digest.problems_attention })
                    : undefined
                }
                danger={digest.problems_attention > 0}
                onOpen={() => go("issues")}
              />
              <Tile
                icon="tasks"
                label={tx("В работе")}
                value={digest.open_runs}
                hint={tx("чек-листов сейчас")}
              />
            </section>

            {digest.overdue_titles.length > 0 && (
              <section className="rounded-card bg-tg-secondary-bg/60 p-3">
                <h2 className="text-sm font-semibold text-tg-text">
                  {tx("Что просрочено")}
                </h2>
                <ul className="mt-2 space-y-1.5">
                  {digest.overdue_titles.map((title) => (
                    <li key={title} className="flex gap-2 text-xs text-tg-text">
                      <span className="mt-0.5 shrink-0 text-tg-hint" aria-hidden>
                        <Icon name="clock" size={14} />
                      </span>
                      <span className="min-w-0">{title}</span>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={() => go("tasks")}
                  className="mt-3 min-h-11 w-full rounded-tile bg-tg-button text-sm font-medium text-tg-button-text"
                >
                  {tx("Открыть поручения")}
                </button>
              </section>
            )}

            <p className="px-1 text-2xs text-tg-hint">
              {tx(
                "Числа считаются по тем же правилам видимости, что журнал и задачи: чужого здесь не показывается.",
              )}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function SkeletonTile() {
  return (
    <div className="rounded-card bg-tg-secondary-bg/60 p-3 animate-pulse motion-reduce:animate-none">
      <div className="h-3 w-2/3 rounded-tile bg-tg-bg/40" />
      <div className="mt-2 h-6 w-10 rounded-tile bg-tg-bg/50" />
    </div>
  );
}

function Tile({
  icon,
  label,
  value,
  hint,
  danger = false,
  onOpen,
}: {
  icon: IconName;
  label: string;
  value: number;
  hint?: string;
  danger?: boolean;
  onOpen?: () => void;
}) {
  const content = (
    <>
      <div className="flex items-center gap-1.5 text-2xs text-tg-hint">
        <Icon name={icon} size={13} />
        <span className="truncate">{label}</span>
      </div>
      <div
        className={[
          "mt-1 text-xl font-semibold tabular-nums",
          danger ? "text-status-busy" : "text-tg-text",
        ].join(" ")}
      >
        {value}
      </div>
      {hint && <div className="mt-0.5 text-2xs text-tg-hint">{hint}</div>}
    </>
  );

  if (!onOpen) {
    return (
      <div className="rounded-card bg-tg-secondary-bg/60 p-3">{content}</div>
    );
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      className="rounded-card bg-tg-secondary-bg/60 p-3 text-left press"
    >
      {content}
    </button>
  );
}
