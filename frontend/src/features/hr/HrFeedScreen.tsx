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
  self: "Только твои отметки.",
  department: "Действия твоего подразделения.",
  all: "Всё предприятие.",
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

/** Заголовок дня для группировки: «Сегодня», «Вчера» или дата. */
function dayLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Без даты";
  const today = new Date();
  const startOf = (x: Date) =>
    new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diffDays = Math.round((startOf(today) - startOf(d)) / 86_400_000);
  if (diffDays === 0) return "Сегодня";
  if (diffDays === 1) return "Вчера";
  return d.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    ...(d.getFullYear() === today.getFullYear() ? {} : { year: "numeric" }),
  });
}

/** Складывает отсортированные записи в группы по календарным дням. */
function groupByDay(items: HrFeedItem[]): { label: string; items: HrFeedItem[] }[] {
  const groups: { label: string; items: HrFeedItem[] }[] = [];
  for (const item of items) {
    const label = dayLabel(item.at);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }
  return groups;
}

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
  // Поиск по списку нужен, когда в предприятии десятки людей: прокручивать
  // <select> в мини-аппе неудобно.
  const [search, setSearch] = useState("");

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
  const needle = search.trim().toLowerCase();
  // Выбранный человек остаётся в списке даже при поиске: иначе <select>
  // показал бы пустое значение и фильтр выглядел бы сброшенным.
  const visibleEmployees = (filters?.employees ?? []).filter(
    (employee) =>
      (departmentId === null || employee.department_id === departmentId) &&
      (needle === "" ||
        employee.id === employeeId ||
        employee.display_name.toLowerCase().includes(needle) ||
        (employee.position ?? "").toLowerCase().includes(needle) ||
        (employee.badge ?? "").toLowerCase().includes(needle)),
  );

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h1 className="text-lg font-semibold text-tg-text">События смены</h1>
          {feed && (
            <span className="shrink-0 rounded-full bg-tg-secondary-bg px-2 py-0.5 text-xs text-tg-hint">
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
                  const next = e.target.value ? Number(e.target.value) : null;
                  setDepartmentId(next);
                  // Сотрудник из другого отдела больше не подходит: без этого
                  // в списке оставались бы его записи, и отдел незаметно
                  // превращался в фильтр по одному человеку.
                  if (next !== null && employeeId !== null) {
                    const chosen = filters.employees.find(
                      (employee) => employee.id === employeeId,
                    );
                    if (chosen && chosen.department_id !== next) {
                      setEmployeeId(null);
                    }
                  }
                }}
                className="min-h-9 min-w-0 flex-1 rounded-tile bg-tg-secondary-bg px-2 text-xs text-tg-text"
              >
                <option value="">Все подразделения</option>
                {filters.departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.emoji ? `${d.emoji} ` : ""}
                    {d.name}
                  </option>
                ))}
              </select>
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Поиск по имени или должности"
                aria-label="Поиск сотрудника"
                className="min-h-9 w-full rounded-tile bg-tg-secondary-bg px-2 text-xs text-tg-text placeholder:text-tg-hint"
              />
              <select
                aria-label="Фильтр по сотруднику"
                value={employeeId ?? ""}
                onChange={(e) => {
                  haptic("light");
                  setEmployeeId(e.target.value ? Number(e.target.value) : null);
                }}
                className="min-h-9 min-w-0 flex-1 rounded-tile bg-tg-secondary-bg px-2 text-xs text-tg-text"
              >
                <option value="">Все сотрудники</option>
                {visibleEmployees.length === 0 && (
                  <option value="" disabled>
                    Никого не нашли
                  </option>
                )}
                {visibleEmployees.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.display_name}
                      {(e.position ?? e.badge)
                        ? ` · ${e.position ?? e.badge}`
                        : ""}
                      {departmentId === null && e.department_id !== null
                        ? ` · ${
                            filters.departments.find(
                              (d) => d.id === e.department_id,
                            )?.name ?? "без отдела"
                          }`
                        : ""}
                    </option>
                  ))}
              </select>
            </div>

            {(employeeId !== null || departmentId !== null || kinds.length > 0) && (
              <button
                type="button"
                onClick={() => {
                  haptic("selection");
                  setEmployeeId(null);
                  setDepartmentId(null);
                  setKinds([]);
                }}
                className="min-h-7 rounded-full px-2.5 text-xs text-tg-link"
              >
                Сбросить фильтры
              </button>
            )}

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
                      "min-h-7 rounded-full px-2.5 text-xs transition-colors",
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
          <p className="mt-2 rounded-tile bg-tg-secondary-bg/60 p-2 text-xs text-tg-hint">
            🔒 Видны только твои действия. Расширенные фильтры доступны
            руководителю подразделения и управляющему.
          </p>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {feedQ.isLoading && <ListSkeleton rows={8} />}

        {!feedQ.isLoading && items.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="text-4xl" aria-hidden>
              📋
            </div>
            <div className="mt-2 text-sm font-medium text-tg-text">
              Пока тихо
            </div>
            <div className="mt-1 text-xs text-tg-hint">
              Здесь появятся отметки и поручения.
            </div>
          </div>
        )}

        {groupByDay(items).map((group) => (
          <section key={group.label}>
            <h2 className="sticky top-0 z-10 -mx-4 bg-tg-bg/95 px-4 py-1 text-xs font-medium text-tg-hint backdrop-blur">
              {group.label}
            </h2>
            <div className="mt-1 divide-y divide-tg-secondary-bg/70 overflow-hidden rounded-card bg-tg-secondary-bg/40">
              {group.items.map((item, i) => (
                <FeedRow
                  key={`${item.kind}-${item.ref_id ?? i}-${item.at}`}
                  item={item}
                  departmentName={
                    filters?.departments.find((d) => d.id === item.department_id)
                      ?.name ?? null
                  }
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function FeedRow({
  item,
  departmentName,
}: {
  item: HrFeedItem;
  departmentName: string | null;
}) {
  return (
    <article className="px-3 py-2.5">
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
          <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-tg-hint">
            <span>{fmtWhen(item.at)}</span>
            {departmentName && <span>· {departmentName}</span>}
            <span>· {KIND_LABEL[item.kind]}</span>
          </div>
        </div>
      </div>
    </article>
  );
}
