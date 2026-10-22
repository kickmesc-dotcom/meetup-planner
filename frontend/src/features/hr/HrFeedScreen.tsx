import { Fragment, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchEmployee,
  fetchFeedFilters,
  fetchHrFeed,
  type FeedKind,
  type HrFeed,
  type HrFeedItem,
} from "@/api/hr";
import Badge from "@/features/hr/Badge";
import EmployeeCardSheet from "@/features/hr/EmployeeCardSheet";
import { departmentTone, personTone } from "@/features/hr/tone";
import ErrorState from "@/components/ErrorState";
import Icon, { type IconName } from "@/components/Icon";
import { ListSkeleton } from "@/components/Skeleton";
import { haptic } from "@/tg/webapp";
import {
  countFreshItems,
  markFeedSeen,
  readFeedSeen,
} from "@/features/hr/feedSeen";

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
 *
 * Раунд 5, что изменилось:
 *  • фильтры — один лист-список вместо двух нативных `<select>` в строке. Там
 *    стрелки сортировки рисовались системой, обрезались по краям и читались
 *    как «криво вставшие» ползунки;
 *  • у каждого человека свой цвет аутлайна вокруг имени, у подразделения — свой
 *    цвет пилюли. В ленте стало видно, где чьи строки;
 *  • тап по имени открывает карточку коллеги (активность — по правилу
 *    видимости профиля).
 */

const SCOPE_TITLE: Record<HrFeed["scope"], string> = {
  self: "Мои действия",
  department: "Моё подразделение",
  all: "Всё предприятие",
};

// VISUAL_AUDIT P2.13: подзаголовок не повторял пилюлю («Всё предприятие» и
// «Всё предприятие.» подряд), а объяснял правило видимости.
const SCOPE_HINT: Record<HrFeed["scope"], string> = {
  self: "Чужих записей здесь нет.",
  department: "Коллеги из других подразделений сюда не попадают.",
  all: "Всё, что происходит на смене.",
};

// P1.4: типы событий — SVG, как и вся навигация. Эмодзи рисовались по-разному
// на Windows/iOS/Android и выбивались из строки рядом с настоящими иконками.
const KIND_ICON: Record<FeedKind, IconName> = {
  checklist_done: "check",
  checklist_item: "checklist",
  task_created: "tasks",
  task_status: "repeat",
  task_photo: "camera",
  task_issue: "alert",
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

/**
 * VISUAL_AUDIT P1.8: тестовый сотрудник помечался трижды в одной строке —
 * префиксом `[BOT]` в имени, плашкой должности и чипом `BOT` внутри неё. Теперь
 * имя чистое, а пул помечается один раз — нейтральным «тест».
 */
const DEMO_PREFIX = "[BOT]";

function isDemoItem(item: HrFeedItem): boolean {
  return item.is_demo ?? item.display_name.trimStart().startsWith(DEMO_PREFIX);
}

function stripDemoPrefix(name: string): string {
  let clean = name.trim();
  while (clean.startsWith(DEMO_PREFIX)) {
    clean = clean.slice(DEMO_PREFIX.length).trim();
  }
  return clean;
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
  // список в мини-аппе неудобно.
  const [search, setSearch] = useState("");
  // Фильтры живут в листе: два селекта в одной строке не влезали на узкий
  // экран, и их системные стрелки обрезались по краям.
  const [filtersOpen, setFiltersOpen] = useState(false);
  // Чью карточку открыли (null — оверлей закрыт).
  const [cardEmployeeId, setCardEmployeeId] = useState<number | null>(null);

  // Чей это просмотр: отметка «новое» хранится на сотрудника, а не на
  // устройство — за одним компьютером могут работать двое.
  const meQ = useQuery({
    queryKey: ["hr-employee"],
    queryFn: fetchEmployee,
    retry: false,
    staleTime: 60_000,
  });
  const myEmployeeId = meQ.data?.id ?? null;
  // `null` — отметки нет (первый визит) или сотрудник ещё не загрузился.
  const [seenAt, setSeenAt] = useState<number | null>(null);

  useEffect(() => {
    if (myEmployeeId === null || seenAt !== null) return;
    // Первый визит: считаем «прочитанным» текущий момент, иначе вся история
    // предприятия выглядела бы новой.
    setSeenAt(readFeedSeen(myEmployeeId) ?? Date.now());
  }, [myEmployeeId, seenAt]);

  useEffect(() => {
    if (myEmployeeId === null) return;
    const employeeId = myEmployeeId;
    // Отметка ставится на выходе: пока экран открыт, свежие события остаются
    // «новыми» и не пропадают из-под курсора.
    return () => markFeedSeen(employeeId);
  }, [myEmployeeId]);

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
  // «Новое» — верхушка ленты новее отметки просмотра. Считаем по тем же
  // строкам, что видит человек (с учётом фильтров): если он смотрит только
  // свои события, чужие не должны попадать в счётчик.
  const freshCount = countFreshItems(items, seenAt);
  const lastFresh = freshCount > 0 ? items[freshCount - 1] ?? null : null;
  const needle = search.trim().toLowerCase();
  // Выбранный человек остаётся в списке даже при поиске: иначе список показал
  // бы пустое значение и фильтр выглядел бы сброшенным.
  const visibleEmployees = (filters?.employees ?? []).filter(
    (employee) =>
      (departmentId === null || employee.department_id === departmentId) &&
      (needle === "" ||
        employee.id === employeeId ||
        employee.display_name.toLowerCase().includes(needle) ||
        (employee.position ?? "").toLowerCase().includes(needle) ||
        (employee.badge ?? "").toLowerCase().includes(needle)),
  );
  const selectedDepartment = filters?.departments.find((d) => d.id === departmentId);
  const selectedEmployee = filters?.employees.find((e) => e.id === employeeId);
  const hasFilters = employeeId !== null || departmentId !== null || kinds.length > 0;

  const resetFilters = () => {
    haptic("selection");
    setEmployeeId(null);
    setDepartmentId(null);
    setKinds([]);
    setSearch("");
  };

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
        <div className="mt-1 flex items-start justify-between gap-2">
          <p className="min-w-0 text-xs text-tg-hint">
            {feed ? SCOPE_HINT[feed.scope] : "Загружаем правила видимости…"}
          </p>
          {freshCount > 0 && (
            <span
              data-testid="feed-fresh-count"
              className="shrink-0 rounded-full bg-tg-link/15 px-2 py-0.5 text-2xs font-medium text-tg-text"
            >
              {freshCount} новых
            </span>
          )}
        </div>

        {canFilter && filters && (
          <div className="mt-3 space-y-2">
            <div className="flex gap-1.5">
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Поиск по имени или должности"
                aria-label="Поиск сотрудника"
                className="min-h-10 min-w-0 flex-1 rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text placeholder:text-tg-hint"
              />
              <button
                type="button"
                aria-expanded={filtersOpen}
                onClick={() => {
                  haptic("selection");
                  setFiltersOpen(true);
                }}
                className="flex min-h-10 shrink-0 items-center gap-1 rounded-tile bg-tg-secondary-bg px-3 text-xs text-tg-text"
              >
                <Icon name="layout" size={16} />
                Фильтр
                {hasFilters && (
                  <span className="grid h-4 min-w-4 place-items-center rounded-full bg-tg-link/15 px-1 text-2xs text-tg-text">
                    {(employeeId !== null ? 1 : 0) + (departmentId !== null ? 1 : 0)}
                  </span>
                )}
              </button>
            </div>

            {/* Выбранное видно сразу: лист закрыт, а фильтр не «залип». */}
            {(selectedDepartment || selectedEmployee) && (
              <div className="flex flex-wrap items-center gap-1.5">
                {selectedDepartment && (
                  <Chip
                    label={`${selectedDepartment.emoji ? `${selectedDepartment.emoji} ` : ""}${selectedDepartment.name}`}
                    onClear={() => {
                      setDepartmentId(null);
                      setEmployeeId(null);
                    }}
                  />
                )}
                {selectedEmployee && (
                  <Chip
                    label={selectedEmployee.display_name}
                    onClear={() => setEmployeeId(null)}
                  />
                )}
              </div>
            )}

            {hasFilters && (
              <button
                type="button"
                onClick={resetFilters}
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
                      setKinds(active ? kinds.filter((x) => x !== k) : [...kinds, k]);
                    }}
                    className={[
                      "min-h-7 rounded-full px-2.5 text-xs transition-colors",
                      // P3.16: фильтр по типам — выбор, а не действие; заливка
                      // главной кнопки остаётся за кнопками-действиями.
                      active
                        ? "bg-tg-link/15 font-medium text-tg-text"
                        : "bg-tg-secondary-bg text-tg-hint",
                    ].join(" ")}
                  >
                    <span className="inline-flex items-center gap-1">
                      <Icon name={KIND_ICON[k]} size={13} />
                      {KIND_LABEL[k]}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {feed && !canFilter && (
          <p className="mt-2 flex items-start gap-1.5 rounded-tile bg-tg-secondary-bg/60 p-2 text-xs text-tg-hint">
            <Icon name="lock" size={14} className="mt-0.5 shrink-0" />
            <span>
              Видны только твои действия. Расширенные фильтры доступны
              руководителю подразделения и управляющему.
            </span>
          </p>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {feedQ.isLoading && <ListSkeleton rows={8} />}

        {!feedQ.isLoading && items.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Icon name="clipboard" size={34} className="text-tg-hint" />
            <div className="mt-2 text-sm font-medium text-tg-text">Пока тихо</div>
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
                <Fragment key={`${item.kind}-${item.ref_id ?? i}-${item.at}`}>
                  <FeedRow
                    item={item}
                    departmentName={
                      filters?.departments.find(
                        (d) => d.id === item.department_id,
                      )?.name ?? null
                    }
                    onOpen={setCardEmployeeId}
                  />
                  {/* Разделитель стоит после последнего нового события, а не
                      после первого: читаешь сверху вниз и видишь границу. */}
                  {item === lastFresh && <FreshDivider count={freshCount} />}
                </Fragment>
              ))}
            </div>
          </section>
        ))}
      </div>

      {filtersOpen && filters && (
        <FiltersSheet
          departments={filters.departments}
          employees={visibleEmployees}
          departmentId={departmentId}
          employeeId={employeeId}
          search={search}
          onSearch={setSearch}
          onDepartment={(id) => {
            haptic("selection");
            setDepartmentId(id);
            if (id !== null && employeeId !== null) {
              const chosen = filters.employees.find((e) => e.id === employeeId);
              if (chosen && chosen.department_id !== id) setEmployeeId(null);
            }
          }}
          onEmployee={(id) => {
            haptic("selection");
            setEmployeeId(id);
          }}
          onReset={resetFilters}
          onClose={() => {
            haptic("light");
            setFiltersOpen(false);
          }}
        />
      )}

      {cardEmployeeId !== null && (
        <EmployeeCardSheet
          employeeId={cardEmployeeId}
          onClose={() => setCardEmployeeId(null)}
        />
      )}
    </div>
  );
}

/**
 * Граница «новые / прочитанные» — приём из лент соцсетей.
 *
 * Без него возвращение в приложение выглядит одинаково всегда: непонятно,
 * что появилось с прошлого визита. Яркой плашкой не делаем: это навигация по
 * времени, а не действие и не тревога.
 */
function FreshDivider({ count }: { count: number }) {
  return (
    <div
      role="separator"
      aria-label={`Новые события: ${count}`}
      className="flex items-center gap-2 bg-tg-link/10 px-3 py-1 text-3xs font-medium text-tg-link"
    >
      <span className="h-px flex-1 bg-tg-link/30" aria-hidden />
      <span>Новые · {count}</span>
      <span className="h-px flex-1 bg-tg-link/30" aria-hidden />
    </div>
  );
}

/** Маленькая пилюля выбранного фильтра с крестиком. */
function Chip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-full bg-tg-link/15 px-2 py-0.5 text-2xs text-tg-text">
      <span className="truncate">{label}</span>
      <button
        type="button"
        onClick={onClear}
        aria-label={`Убрать фильтр ${label}`}
        className="shrink-0 text-tg-hint"
      >
        <Icon name="close" size={12} />
      </button>
    </span>
  );
}

/**
 * Лист фильтров: подразделение и сотрудник списками.
 *
 * Почему не `<select>`: нативный селект рисует стрелку сам, её нельзя ни
 * выровнять, ни покрасить, а в узкой строке она обрезалась — на скриншоте это
 * выглядело как «криво вставшие» стрелки сортировки. Список ещё и удобнее:
 * видно отдел каждого человека.
 */
function FiltersSheet({
  departments,
  employees,
  departmentId,
  employeeId,
  search,
  onSearch,
  onDepartment,
  onEmployee,
  onReset,
  onClose,
}: {
  departments: { id: number; name: string; emoji: string | null }[];
  employees: { id: number; display_name: string; department_id: number | null; position: string | null; badge: string | null }[];
  departmentId: number | null;
  employeeId: number | null;
  search: string;
  onSearch: (value: string) => void;
  onDepartment: (id: number | null) => void;
  onEmployee: (id: number | null) => void;
  onReset: () => void;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-40 flex flex-col justify-end" role="dialog" aria-modal="true" aria-label="Фильтры ленты">
      <button
        type="button"
        aria-label="Закрыть фильтры"
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      <div className="relative max-h-[85%] overflow-y-auto rounded-t-card bg-tg-bg p-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-tg-text">Фильтры</h2>
          <button
            type="button"
            onClick={onClose}
            className="grid min-h-9 min-w-9 place-items-center rounded-tile bg-tg-secondary-bg/60 text-tg-text"
            aria-label="Закрыть"
          >
            <Icon name="close" size={16} />
          </button>
        </div>

        <h3 className="mt-3 text-2xs font-medium uppercase tracking-wide text-tg-hint">
          Подразделение
        </h3>
        <div className="mt-1 space-y-1">
          <FilterRow
            active={departmentId === null}
            label="Все подразделения"
            onSelect={() => onDepartment(null)}
          />
          {departments.map((department) => (
            <FilterRow
              key={department.id}
              active={departmentId === department.id}
              label={`${department.emoji ? `${department.emoji} ` : ""}${department.name}`}
              tone={departmentTone(department.id)}
              onSelect={() => onDepartment(department.id)}
            />
          ))}
        </div>

        <h3 className="mt-4 text-2xs font-medium uppercase tracking-wide text-tg-hint">
          Сотрудник
        </h3>
        <input
          type="search"
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder="Поиск по имени или должности"
          aria-label="Поиск сотрудника в фильтре"
          className="mt-1 min-h-9 w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text placeholder:text-tg-hint"
        />
        <div className="mt-1 space-y-1">
          <FilterRow
            active={employeeId === null}
            label="Все сотрудники"
            onSelect={() => onEmployee(null)}
          />
          {employees.length === 0 && (
            <p className="px-2 py-1 text-xs text-tg-hint">Никого не нашли.</p>
          )}
          {employees.map((employee) => (
            <FilterRow
              key={employee.id}
              active={employeeId === employee.id}
              label={employee.display_name}
              hint={employee.position ?? employee.badge ?? undefined}
              tone={personTone(employee.id)}
              onSelect={() => onEmployee(employee.id)}
            />
          ))}
        </div>

        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => {
              onReset();
              onClose();
            }}
            className="min-h-11 flex-1 rounded-tile bg-tg-secondary-bg text-sm text-tg-text"
          >
            Сбросить
          </button>
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 flex-1 rounded-tile bg-tg-button text-sm font-medium text-tg-button-text"
          >
            Готово
          </button>
        </div>
      </div>
    </div>
  );
}

function FilterRow({
  active,
  label,
  hint,
  tone,
  onSelect,
}: {
  active: boolean;
  label: string;
  hint?: string;
  tone?: { border: string; soft: string };
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onSelect}
      className={[
        "flex min-h-10 w-full items-center gap-2 rounded-tile px-2 text-left text-sm",
        active ? "bg-tg-link/15 font-medium text-tg-text" : "text-tg-text",
      ].join(" ")}
    >
      {tone && (
        <span
          className="h-3 w-3 shrink-0 rounded-full"
          style={{ backgroundColor: tone.soft, border: `2px solid ${tone.border}` }}
          aria-hidden
        />
      )}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {hint && <span className="shrink-0 text-2xs text-tg-hint">{hint}</span>}
      {active && <Icon name="check" size={14} className="shrink-0 text-tg-link" />}
    </button>
  );
}

function FeedRow({
  item,
  departmentName,
  onOpen,
}: {
  item: HrFeedItem;
  departmentName: string | null;
  onOpen: (employeeId: number) => void;
}) {
  const demo = isDemoItem(item);
  const person = personTone(item.employee_id);
  const dept = departmentTone(item.department_id);
  const name = stripDemoPrefix(item.display_name);

  return (
    <article className="px-3 py-2.5">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 shrink-0 text-tg-hint" aria-hidden>
          <Icon name={KIND_ICON[item.kind]} size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm text-tg-text break-words">
            <button
              type="button"
              disabled={item.employee_id === null}
              onClick={() => {
                if (item.employee_id === null) return;
                haptic("light");
                onOpen(item.employee_id);
              }}
              // Аутлайн вокруг имени: у каждого человека свой цвет, поэтому
              // видно, где кончаются действия одного и начинаются другого.
              className="inline-flex max-w-full items-center rounded-full px-2 py-0.5 align-middle font-medium text-tg-text active:opacity-70 disabled:opacity-100"
              style={{
                backgroundColor: person.soft,
                border: `1px solid ${person.border}`,
              }}
            >
              <span className="truncate">{name}</span>
            </button>{" "}
            {demo ? (
              // Одна пометка на всю строку: ни плашки, ни префикса в имени.
              <span
                data-testid="feed-demo-mark"
                title="Тестовый сотрудник"
                className="inline-flex items-center rounded-full bg-tg-bg/70 px-1.5 py-0.5 align-middle text-2xs font-medium text-tg-hint"
              >
                тест
              </span>
            ) : (
              <Badge
                text={item.badge}
                emoji={item.badge_emoji}
                tone={dept}
              />
            )}{" "}
            {item.text}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-tg-hint">
            <span>{fmtWhen(item.at)}</span>
            <span>· {KIND_LABEL[item.kind]}</span>
            {departmentName && (
              // Подразделение — своей пилюлей: в ленте видно, откуда человек,
              // даже если у него нет плашки должности.
              <span
                className="inline-flex max-w-full items-center rounded-full px-1.5 text-2xs text-tg-text"
                style={{ backgroundColor: dept.soft, border: `1px solid ${dept.border}` }}
              >
                <span className="truncate">{departmentName}</span>
              </span>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
