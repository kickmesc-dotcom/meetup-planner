import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchFeedFilters,
  fetchHrFeed,
  type FeedKind,
  type HrFeed,
  type HrFeedItem,
} from "@/api/hr";
import Badge from "@/features/hr/Badge";
import ErrorState from "@/components/ErrorState";
import { ListSkeleton } from "@/components/Skeleton";
import { haptic } from "@/tg/webapp";

/**
 * SemiTaskBot: «События смены» — лента с ролевой видимостью.
 *
 * Строгое правило (одно на бота и на мини-апп):
 *   • сотрудник — только свои действия;
 *   • руководитель подразделения — действия подчинённых своего подразделения;
 *   • управляющий — всё, с фильтром по сотруднику и подразделению.
 *
 * Экран НЕ решает, что показать: `scope` и `can_filter` приходят с сервера, и
 * фильтры рисуются только тогда, когда сервер их разрешает. Скрытие кнопки —
 * лишь удобство: сам ответ уже отфильтрован по роли, а попытка выбрать чужого
 * сотрудника вернёт 403, а не чужие записи.
 */

const SCOPE_TITLE: Record<HrFeed["scope"], string> = {
  self: "Мои действия",
  department: "Моё подразделение",
  all: "Всё предприятие",
};

const SCOPE_HINT: Record<HrFeed["scope"], string> = {
  self: "Здесь только твои отметки: чек-лист, поручения, фотоотчёты.",
  department: "Действия сотрудников твоего подразделения и твои собственные.",
  all: "Все действия предприятия. Фильтруй по сотруднику и подразделению.",
};

const KIND_ICON: Record<FeedKind, string> = {
  checklist_done: "🗒",
  checklist_item: "✅",
  task_created: "📌",
  task_status: "🔄",
  task_photo: "📷",
  task_issue: "⚠️",
};

const KIND_LABEL: Record<FeedKind, string> = {
  checklist_done: "Чек-лист закрыт",
  checklist_item: "Пункт чек-листа",
  task_created: "Поручение",
  task_status: "Статус поручения",
  task_photo: "Фотоотчёт",
  task_issue: "Проблема",
};

function fmtWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = Date.now();
  const diff = Math.max(0, now - d.getTime());
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "только что";
  if (min < 60) return `${min} мин назад`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours} ч назад`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "вчера";
  if (days < 7) return `${days} дн. назад`;
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function HrFeedScreen() {
  const [employeeId, setEmployeeId] = useState<number | null>(null);
  const [departmentId, setDepartmentId] = useState<number | null>(null);
  const [kinds, setKinds] = useState<FeedKind[]>([]);

  const filtersQ = useQuery({
    queryKey: ["hr-feed-filters"],
    queryFn: fetchFeedFilters,
    staleTime: 5 * 60 * 1000,
  });

  const feedQ = useQuery({
    queryKey: ["hr-feed", employeeId, departmentId, kinds.join(",")],
    queryFn: () =>
      fetchHrFeed({
        employeeId,
        departmentId,
        kinds: kinds.length ? kinds : undefined,
        limit: 100,
      }),
  });

  if (feedQ.isError) {
    const err = feedQ.error;
    // 403 = выбранный сотрудник вне области видимости. Это не «поломка», а
    // честный отказ сервера — показываем его текстом и сбрасываем фильтр.
    return (
      <ErrorState
        error={err}
        onRetry={() => {
          setEmployeeId(null);
          setDepartmentId(null);
          void feedQ.refetch();
        }}
        title="Лента недоступна"
      />
    );
  }

  const feed = feedQ.data;
  const filters = filtersQ.data;
  const canFilter = feed?.can_filter === true;
  const items = feed?.items ?? [];

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h1 className="text-lg font-semibold text-tg-text">События смены</h1>
          {feed && (
            <span className="shrink-0 rounded-full bg-tg-secondary-bg px-2 py-0.5 text-[11px] text-tg-hint">
              {SCOPE_TITLE[feed.scope]}
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-tg-hint">
          {feed ? SCOPE_HINT[feed.scope] : "Загружаем правила видимости…"}
        </p>

        {canFilter && filters && (
          <div className="mt-3 space-y-2">
            <div className="flex gap-1.5">
              <select
                aria-label="Фильтр по подразделению"
                value={departmentId ?? ""}
                onChange={(e) => {
                  haptic("light");
                  setDepartmentId(
                    e.target.value ? Number(e.target.value) : null,
                  );
                }}
                className="min-h-9 min-w-0 flex-1 rounded-lg bg-tg-secondary-bg px-2 text-xs text-tg-text"
              >
                <option value="">Все подразделения</option>
                {filters.departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.emoji ? `${d.emoji} ` : ""}
                    {d.name}
                  </option>
                ))}
              </select>
              <select
                aria-label="Фильтр по сотруднику"
                value={employeeId ?? ""}
                onChange={(e) => {
                  haptic("light");
                  setEmployeeId(e.target.value ? Number(e.target.value) : null);
                }}
                className="min-h-9 min-w-0 flex-1 rounded-lg bg-tg-secondary-bg px-2 text-xs text-tg-text"
              >
                <option value="">Все сотрудники</option>
                {filters.employees
                  .filter(
                    (e) =>
                      departmentId === null || e.department_id === departmentId,
                  )
                  .map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.display_name}
                    </option>
                  ))}
              </select>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {filters.kinds.map((k) => {
                const active = kinds.includes(k);
                return (
                  <button
                    key={k}
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      haptic("selection");
                      setKinds(
                        active ? kinds.filter((x) => x !== k) : [...kinds, k],
                      );
                    }}
                    className={[
                      "min-h-7 rounded-full px-2.5 text-[11px] transition-colors",
                      active
                        ? "bg-tg-button text-tg-button-text"
                        : "bg-tg-secondary-bg text-tg-hint",
                    ].join(" ")}
                  >
                    {KIND_ICON[k]} {KIND_LABEL[k]}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {feed && !canFilter && (
          <p className="mt-2 rounded-lg bg-tg-secondary-bg/60 p-2 text-[11px] text-tg-hint">
            🔒 Видны только твои действия. Расширенные фильтры доступны
            руководителю подразделения и управляющему.
          </p>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {feedQ.isLoading && <ListSkeleton rows={8} />}

        {!feedQ.isLoading && items.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="text-4xl" aria-hidden>
              📋
            </div>
            <div className="mt-2 text-sm font-medium text-tg-text">
              Событий нет
            </div>
            <div className="mt-1 text-xs text-tg-hint">
              Как только появятся отметки чек-листа или движения по поручениям,
              они окажутся здесь.
            </div>
          </div>
        )}

        {items.map((item, i) => (
          <FeedRow
            key={`${item.kind}-${item.ref_id ?? i}-${item.at}`}
            item={item}
          />
        ))}
      </div>
    </div>
  );
}

function FeedRow({ item }: { item: HrFeedItem }) {
  return (
    <article className="rounded-xl bg-tg-secondary-bg/60 p-3">
      <div className="flex items-start gap-2">
        <span className="text-base" aria-hidden>
          {KIND_ICON[item.kind]}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm text-tg-text break-words">
            <span className="font-medium">{item.display_name}</span>{" "}
            <Badge
              text={item.badge}
              emoji={item.badge_emoji}
              demo={item.display_name.startsWith("[BOT]")}
            />{" "}
            {item.text}
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-tg-hint">
            <span>{fmtWhen(item.at)}</span>
            <span>· {KIND_LABEL[item.kind]}</span>
          </div>
        </div>
      </div>
    </article>
  );
}
