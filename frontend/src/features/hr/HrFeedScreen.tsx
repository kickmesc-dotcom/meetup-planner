import { Fragment, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchDepartments,
  fetchEmployee,
  fetchFeedFilters,
  fetchHrFeed,
  type FeedKind,
  type HrFeed,
  type HrFeedItem,
} from "@/api/hr";
import Badge from "@/features/hr/Badge";
import EmployeeCardSheet from "@/features/hr/EmployeeCardSheet";
import KudosCard from "@/features/hr/KudosCard";
import DepartmentScreen from "@/features/hr/DepartmentScreen";
import { departmentTone, personTone } from "@/features/hr/tone";
import ErrorState from "@/components/ErrorState";
import Icon, { type IconName } from "@/components/Icon";
import {
  TRANSLATED_MARK_INLINE,
  TranslateBlockButton,
  TranslateFailedNotice,
  useBatchTranslate,
} from "@/components/TranslatableBlock";
import { ListSkeleton, Skeleton } from "@/components/Skeleton";
import { haptic } from "@/tg/webapp";
import { currentIntlLocale, intlLocaleFor, tx, useTx, type Locale } from "@/i18n";
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
  kudos: "sparkles",
};

const KIND_LABEL: Record<FeedKind, string> = {
  checklist_done: "Чек-лист закрыт",
  checklist_item: "Пункт чек-листа",
  task_created: "Поручение",
  task_status: "Статус поручения",
  task_photo: "Фотоотчёт",
  task_issue: "Проблема",
  kudos: "Поблагодарил(а) коллегу",
};

/**
 * Заголовок дня — всегда абсолютная дата, без «сегодня»/«вчера».
 *
 * Относительные подписи в ленте смен сбивают: «вчера» через сутки означает
 * уже другой день, а при разборе конфликта важно, какое именно число. Поэтому
 * в разделителе стоит дата, а у каждой записи — точное время с секундами.
 */
function dayLabel(iso: string, locale: Locale): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return tx(locale, "Без даты");
  const today = new Date();
  // Формат берём у Intl, а не склеиваем руками: в английском день недели
  // стоит перед числом («Wednesday, 21 October»), и переставлять его
  // вручную — это гарантированная ошибка в одном из двух языков.
  return d.toLocaleDateString(intlLocaleFor(locale), {
    day: "numeric",
    month: "long",
    weekday: "long",
    ...(d.getFullYear() === today.getFullYear() ? {} : { year: "numeric" }),
  });
}

/** Ключ дня в местном времени: по нему идёт группировка, не по тексту. */
function dayKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "none";
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

/** Складывает отсортированные записи в группы по календарным дням. */
function groupByDay(
  items: HrFeedItem[],
  locale: Locale,
): { key: string; label: string; items: HrFeedItem[] }[] {
  const groups: { key: string; label: string; items: HrFeedItem[] }[] = [];
  for (const item of items) {
    const key = dayKey(item.at);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(item);
    else groups.push({ key, label: dayLabel(item.at, locale), items: [item] });
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

/**
 * Точное время события: часы, минуты и секунды.
 *
 * Не «5 мин назад»: в ленте смены два события могут стоять рядом, и по
 * относительной подписи невозможно понять, что было раньше, а что позже.
 * Секунды нужны при разборе («во сколько закрыли чек-лист») и не мешают: они
 * моноширинно выровнены в строке.
 */
function fmtWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function HrFeedScreen() {
  const { tx, locale } = useTx();
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
  // Какое подразделение открыли дашбордом (тап по плашке в ленте).
  const [cardDepartmentId, setCardDepartmentId] = useState<number | null>(null);

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
  // Справочник подразделений нужен и сотруднику: список фильтров у него пуст
  // (фильтровать нечего), но плашка отдела в строке должна открывать дашборд
  // своего подразделения. Имя отдела берём из этого справочника.
  const depsQ = useQuery({
    queryKey: ["hr-departments"],
    queryFn: fetchDepartments,
    staleTime: 5 * 60 * 1000,
  });

  const feedQ = useQuery({
    // Локаль — часть ключа: фразу записи собирает сервер, поэтому при смене
    // языка ленту надо перезапросить, а не переводить уже полученный текст.
    queryKey: ["hr-feed", employeeId, departmentId, kinds.join(","), locale],
    queryFn: () =>
      fetchHrFeed({
        employeeId,
        departmentId,
        kinds: kinds.length ? kinds : undefined,
        limit: 100,
        lang: locale,
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
        title={tx("Лента недоступна")}
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

  const scrollerRef = useRef<HTMLDivElement | null>(null);

  /**
   * Прокрутка к нужному дню по стрелкам в плашке.
   *
   * Считаем от текущего `scrollTop` и живого положения секции, а не по
   * сохранённым координатам: лента перерисовывается (фильтры, новые события),
   * и запомненный `top` устарел бы. Плавность отключаем при
   * `prefers-reduced-motion` — как и переход вкладок.
   */
  const jumpToDay = (index: number) => {
    const box = scrollerRef.current;
    const days = box?.querySelectorAll<HTMLElement>("[data-day]");
    const target = days?.[index];
    if (!box || !target) return;
    haptic("selection");
    const next =
      box.scrollTop +
      target.getBoundingClientRect().top -
      box.getBoundingClientRect().top;
    const reduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (typeof box.scrollTo === "function") {
      box.scrollTo({ top: next, behavior: reduced ? "auto" : "smooth" });
    } else {
      box.scrollTop = next;
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h1 className="text-lg font-semibold text-tg-text">{tx("События смены")}</h1>
          {feed && (
            <span className="shrink-0 rounded-full bg-tg-secondary-bg px-2 py-0.5 text-xs text-tg-hint">
              {tx(SCOPE_TITLE[feed.scope])}
            </span>
          )}
        </div>
        <div className="mt-1 flex items-start justify-between gap-2">
          {/* Подпись о видимости — статика из данных ленты: до ответа на её
              месте строка-скелетон той же высоты (правило 9.1). */}
          {feed ? (
            <p className="min-w-0 text-xs text-tg-hint">{tx(SCOPE_HINT[feed.scope])}</p>
          ) : (
            <Skeleton className="h-3 w-2/3" />
          )}
          {freshCount > 0 && (
            <span
              data-testid="feed-fresh-count"
              className="shrink-0 rounded-full bg-tg-link/15 px-2 py-0.5 text-2xs font-medium text-tg-text"
            >
              {tx("{count} новых", { count: freshCount })}
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
                placeholder={tx("Поиск по имени или должности")}
                aria-label={tx("Поиск сотрудника")}
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
                {tx("Фильтр")}
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
                {tx("Сбросить фильтры")}
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
                      {tx(KIND_LABEL[k])}
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
              {tx("Видны только твои действия. Расширенные фильтры доступны руководителю подразделения и управляющему.")}
            </span>
          </p>
        )}
      </header>

      <div
        ref={scrollerRef}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-3"
      >
        {feedQ.isLoading && <ListSkeleton rows={8} />}

        {!feedQ.isLoading && items.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Icon name="clipboard" size={34} className="text-tg-hint" />
            <div className="mt-2 text-sm font-medium text-tg-text">{tx("Пока тихо")}</div>
            <div className="mt-1 text-xs text-tg-hint">
              {tx("Здесь появятся отметки и поручения.")}
            </div>
          </div>
        )}

        {/* Благодарности — над лентой: за неделю их немного, и они мотивируют
            сильнее, чем ещё одна строка в потоке событий. Карточка идёт после
            пустого состояния, чтобы не сдвигать его вниз при пустой ленте. */}
        {!feedQ.isLoading && <KudosCard />}

        {groupByDay(items, locale).map((group, index, allGroups) => (
          <FeedDay
            key={group.key}
            group={group}
            index={index}
            dayCount={allGroups.length}
            departmentNameFor={(departmentId: number | null) =>
              filters?.departments.find((d) => d.id === departmentId)?.name ??
              depsQ.data?.find((d) => d.id === departmentId)?.name ??
              null
            }
            lastFresh={lastFresh}
            freshCount={freshCount}
            onJumpDay={jumpToDay}
            onOpenEmployee={setCardEmployeeId}
            onOpenDepartment={setCardDepartmentId}
          />
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

      {cardDepartmentId !== null && (
        <DepartmentScreen
          departmentId={cardDepartmentId}
          onClose={() => setCardDepartmentId(null)}
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
  const { tx } = useTx();
  return (
    <div
      role="separator"
      aria-label={tx("Новые события: {count}", { count })}
      className="flex items-center gap-2 bg-tg-link/10 px-3 py-1 text-3xs font-medium text-tg-link"
    >
      <span className="h-px flex-1 bg-tg-link/30" aria-hidden />
      <span>{tx("Новые · {count}", { count })}</span>
      <span className="h-px flex-1 bg-tg-link/30" aria-hidden />
    </div>
  );
}

/** Маленькая пилюля выбранного фильтра с крестиком. */
function Chip({ label, onClear }: { label: string; onClear: () => void }) {
  const { tx } = useTx();
  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-full bg-tg-link/15 px-2 py-0.5 text-2xs text-tg-text">
      <span className="truncate">{label}</span>
      <button
        type="button"
        onClick={onClear}
        aria-label={tx("Убрать фильтр {label}", { label })}
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
  const { tx } = useTx();
  return (
    <div className="fixed inset-0 z-40 flex flex-col justify-end" role="dialog" aria-modal="true" aria-label={tx("Фильтры ленты")}>
      <button
        type="button"
        aria-label={tx("Закрыть фильтры")}
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      <div className="relative max-h-[85%] overflow-y-auto rounded-t-card bg-tg-bg p-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-tg-text">{tx("Фильтры")}</h2>
          <button
            type="button"
            onClick={onClose}
            className="grid min-h-9 min-w-9 place-items-center rounded-tile bg-tg-secondary-bg/60 text-tg-text"
            aria-label={tx("Закрыть")}
          >
            <Icon name="close" size={16} />
          </button>
        </div>

        <h3 className="mt-3 text-2xs font-medium uppercase tracking-wide text-tg-hint">
          {tx("Подразделение")}
        </h3>
        <div className="mt-1 space-y-1">
          <FilterRow
            active={departmentId === null}
            label={tx("Все подразделения")}
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
          {tx("Сотрудник")}
        </h3>
        <input
          type="search"
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder={tx("Поиск по имени или должности")}
          aria-label={tx("Поиск сотрудника в фильтре")}
          className="mt-1 min-h-9 w-full rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text placeholder:text-tg-hint"
        />
        <div className="mt-1 space-y-1">
          <FilterRow
            active={employeeId === null}
            label={tx("Все сотрудники")}
            onSelect={() => onEmployee(null)}
          />
          {employees.length === 0 && (
            <p className="px-2 py-1 text-xs text-tg-hint">{tx("Никого не нашли.")}</p>
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
            {tx("Сбросить")}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 flex-1 rounded-tile bg-tg-button text-sm font-medium text-tg-button-text"
          >
            {tx("Готово")}
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

/**
 * Один день ленты: плашка дня, навигация по дням и кнопка перевода — одна на
 * весь день (план, 11.5).
 *
 * Почему кнопка на день, а не на строку. В дне два десятка событий; иконка
 * «перевести» в каждом — это стена одинаковых кнопок, которая мешает читать и
 * не помогает: человеку нужен весь день на своём языке сразу. Один запрос
 * переводит все видимые события дня пачкой (ручка принимает до 20 строк).
 *
 * Компонент отдельный, а не кусок разметки в `map`: режим перевода — это
 * состояние (хук), а хуки внутри цикла вызывать нельзя.
 */
function FeedDay({
  group,
  index,
  dayCount,
  departmentNameFor,
  lastFresh,
  freshCount,
  onJumpDay,
  onOpenEmployee,
  onOpenDepartment,
}: {
  group: { key: string; label: string; items: HrFeedItem[] };
  index: number;
  dayCount: number;
  departmentNameFor: (departmentId: number | null) => string | null;
  lastFresh: HrFeedItem | null;
  freshCount: number;
  onJumpDay: (index: number) => void;
  onOpenEmployee: (employeeId: number) => void;
  onOpenDepartment: (departmentId: number) => void;
}) {
  const { tx } = useTx();
  const translate = useBatchTranslate(group.items.map((item) => item.text));

  return (
    <section data-day={group.key}>
      {/* Плашка дня закреплена сверху и сменяется, когда начинается
          следующая дата. Раньше это была полупрозрачная строка с
          линией: содержимое просвечивало сквозь неё, и день читался
          как ещё одна запись ленты. Теперь это отдельная подложка на
          непрозрачном фоне — по ней видно, где ты находишься. */}
      <h2 className="sticky top-0 z-10 -mx-4 flex items-center gap-2 bg-tg-bg px-4 py-1">
        <span
          data-testid="feed-day"
          className="flex min-w-0 items-center gap-1.5 rounded-full bg-tg-secondary-bg px-3 py-1.5 text-xs font-semibold text-tg-text shadow-sm"
        >
          <Icon
            name="calendar"
            size={13}
            className="shrink-0 text-tg-hint"
          />
          <span className="truncate">{group.label}</span>
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-1">
          {translate.canTranslate && (
            <TranslateBlockButton
              on={translate.on}
              busy={translate.busy}
              onClick={() => void translate.toggle()}
            />
          )}
          <button
            type="button"
            data-testid="feed-prev-day"
            aria-label={tx("Предыдущий день")}
            title={tx("Предыдущий день")}
            disabled={index >= dayCount - 1}
            onClick={() => onJumpDay(index + 1)}
            className="grid h-9 w-9 place-items-center rounded-full bg-tg-secondary-bg text-tg-text transition press disabled:opacity-35 disabled:press"
          >
            <Icon name="back" size={16} />
          </button>
          <button
            type="button"
            data-testid="feed-next-day"
            aria-label={tx("Следующий день")}
            title={tx("Следующий день")}
            disabled={index === 0}
            onClick={() => onJumpDay(index - 1)}
            className="grid h-9 w-9 place-items-center rounded-full bg-tg-secondary-bg text-tg-text transition press disabled:opacity-35 disabled:press"
          >
            <Icon name="chevron" size={16} />
          </button>
        </span>
      </h2>
      {/* Отказ стоит здесь, а не в закреплённой шапке: он не должен ни
          растягивать плашку дня, ни теряться при прокрутке вместе с ней. */}
      <TranslateFailedNotice show={translate.failed} />
      <div className="mt-1.5 divide-y divide-tg-secondary-bg/70 overflow-hidden rounded-card bg-tg-secondary-bg/40">
        {group.items.map((item, i) => {
          const shown = translate.t(item.text);
          return (
            <Fragment key={`${item.kind}-${item.ref_id ?? i}-${item.at}`}>
              <FeedRow
                item={item}
                text={shown}
                translated={shown !== item.text}
                departmentName={departmentNameFor(item.department_id)}
                onOpen={onOpenEmployee}
                onOpenDepartment={onOpenDepartment}
              />
              {/* Разделитель стоит после последнего нового события, а не
                  после первого: читаешь сверху вниз и видишь границу. */}
              {item === lastFresh && <FreshDivider count={freshCount} />}
            </Fragment>
          );
        })}
      </div>
    </section>
  );
}

function FeedRow({
  item,
  text,
  translated,
  departmentName,
  onOpen,
  onOpenDepartment,
}: {
  item: HrFeedItem;
  /** Текст события: оригинал либо перевод, если в дне включён режим. */
  text: string;
  /** Признак перевода — для подложки, чтобы машинный текст не читался как авторский. */
  translated: boolean;
  departmentName: string | null;
  onOpen: (employeeId: number) => void;
  onOpenDepartment: (departmentId: number) => void;
}) {
  const { tx } = useTx();
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
                title={tx("Тестовый сотрудник")}
                className="inline-flex items-center rounded-full bg-tg-bg/70 px-1.5 py-0.5 align-middle text-2xs font-medium text-tg-hint"
              >
                {tx("тест")}
              </span>
            ) : (
              <Badge
                text={item.badge}
                emoji={item.badge_emoji}
                tone={dept}
              />
            )}{" "}
            <span
              // Цвет акцента, как у активного глобуса в плашке дня: иначе
              // подложка сливалась с карточкой, и перевод читался как оригинал.
              className={translated ? TRANSLATED_MARK_INLINE : undefined}
            >
              {text}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-tg-hint">
            <time
              dateTime={item.at}
              title={new Date(item.at).toLocaleString(currentIntlLocale())}
              className="tabular-nums"
            >
              {fmtWhen(item.at)}
            </time>
            <span>· {tx(KIND_LABEL[item.kind])}</span>
            {departmentName && (
              // Подразделение — своей пилюлей и КНОПКОЙ: тап открывает
              // дашборд отдела (кто в смене, у кого что не закрыто). Раньше
              // это был просто текст, и из ленты нельзя было перейти к людям.
              <button
                type="button"
                disabled={item.department_id === null}
                onClick={() => {
                  if (item.department_id === null) return;
                  haptic("selection");
                  onOpenDepartment(item.department_id);
                }}
                className="inline-flex max-w-full items-center gap-0.5 rounded-full px-1.5 text-2xs text-tg-text active:opacity-70 disabled:active:opacity-100"
                style={{ backgroundColor: dept.soft, border: `1px solid ${dept.border}` }}
                aria-label={tx("Открыть подразделение {name}", { name: departmentName })}
              >
                <span className="truncate">{departmentName}</span>
                <Icon name="chevron" size={10} className="shrink-0 opacity-60" />
              </button>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
