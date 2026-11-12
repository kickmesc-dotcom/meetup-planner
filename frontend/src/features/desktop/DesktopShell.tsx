import type { ReactNode } from "react";
import Icon, { type IconName } from "@/components/Icon";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import { useTerms } from "@/api/texts";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import { useUI, type Tab } from "@/store/ui";
import { sectionEnabled } from "@/features/hr/sections";
import { haptic } from "@/tg/webapp";
import { useTx } from "@/i18n";
/**
 * Каркас широкого экрана (≥1024px).
 *
 * Мобильная версия остаётся как была: колонка 560px и нижняя полоса. На ПК
 * (растянутое окно Telegram Desktop или прямая ссылка в браузере) открывается
 * эта оболочка — постоянный сайдбар и широкая рабочая область.
 *
 * 04.11.2026: каркас стал **одним для обеих зон**. Раньше зона сотрудника
 * рисовала сайдбар, а зона управления — свой заголовок и нижнюю полосу, и на
 * десктопе навигация прыгала из левого столбца в нижнюю строку при
 * переключении «Сотрудник | Управление». Жалоба владельца была именно об этом:
 * разные блоки, разная логика расположения, даже кнопки переключателя зон
 * переезжают. Теперь правило жёсткое: слева — сайдбар, сверху — переключатель
 * зон, снизу — ничего; нижняя полоса существует только на узком экране.
 *
 * `zone="manage"` меняет не каркас, а только содержимое сайдбара: в управлении
 * это «Кабинет · Внимание · Поручения · Приёмка · Настройки». Один и тот же
 * человек, переключая зону, остаётся в том же месте экрана.
 */

interface NavItem {
  id: Tab;
  label: string;
  icon: IconName;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

interface AdminItem {
  id: string;
  label: string;
  icon: IconName;
  manager?: boolean;
}

const WORK: NavItem[] = [
  { id: "feed", label: "События", icon: "feed" },
  { id: "tasks", label: "Мои задачи", icon: "tasks" },
  { id: "checklist", label: "Чек-лист смены", icon: "clipboard" },
  // «График» — это расписание смен. Раньше здесь стояло «Табель» (сводка
  // часов), а рядом в «Сервисе» жил «Календарь» — сетка свободного времени
  // старого планировщика с людьми, которых в смене уже нет. Одна неделя
  // работы вместо двух экранов.
  { id: "shifts", label: "График", icon: "calendar" },
  { id: "materials", label: "Материалы", icon: "book" },
  // Проблемы и передачи смены — часть рабочего дня, а не надзор. Пока они
  // стояли отдельной группой «Команда», группа называлась не по делу.
  { id: "issues", label: "Проблемы", icon: "alert" },
  { id: "handovers", label: "Передачи смены", icon: "repeat" },
];

const SERVICE: NavItem[] = [
  { id: "meetings", label: "Встречи и опросы", icon: "clock" },
  { id: "standards", label: "Стандарты", icon: "checklist" },
  { id: "links", label: "Ссылки", icon: "globe" },
];

const PROFILE: NavItem = { id: "profile", label: "Профиль", icon: "profile" };

const ADMIN_ITEMS: AdminItem[] = [
  { id: "root", label: "Кабинет", icon: "layout" },
  { id: "attention", label: "Внимание", icon: "alert" },
  { id: "admin-tasks", label: "Поручения", icon: "clipboard" },
  { id: "review", label: "Приёмка", icon: "check", manager: true },
];

const ADMIN_SETTINGS: AdminItem = { id: "settings", label: "Настройки", icon: "settings" };

export default function DesktopShell({
  meName,
  meHint,
  openTasks = 0,
  sections,
  zone = "staff",
  canManage = false,
  platform = false,
  children,
}: {
  /** Разделы из настройки организации (undefined — ничего не прячем). */
  sections?: string[];
  meName: string;
  meHint: string;
  /** Открытые поручения — счётчик рядом с «Мои задачи», как в соцсетях. */
  openTasks?: number;
  /** `manage` — зона управления: тот же каркас, другой сайдбар. */
  zone?: "staff" | "manage";
  canManage?: boolean;
  platform?: boolean;
  children: ReactNode;
}) {
  const { tx } = useTx();
  const term = useTerms();
  const tab = useUI((s) => s.tab);
  const setTab = useUI((s) => s.setTab);
  const adminSection = useUI((s) => s.adminSection);
  const setAdminSection = useUI((s) => s.setAdminSection);
  const setMode = useUI((s) => s.setMode);

  const keep = (items: NavItem[]) =>
    sections ? items.filter((item) => sectionEnabled(item.id, sections)) : items;
  // Группы сотрудника: 02.11.2026 команда, приёмка и отчёт переехали в зону
  // управления, поэтому «Команды» здесь больше нет.
  const staffGroups: NavGroup[] = [
    { title: term("shift.one", tx("Смена")), items: keep(WORK) },
    { title: tx("Сервис"), items: keep([...SERVICE, PROFILE]) },
  ];

  const adminItems = ADMIN_ITEMS.filter(
    (item) => !item.manager || canManage || platform,
  );
  const manage = zone === "manage";

  return (
    <div className="flex h-full min-h-0 w-full" data-testid="desktop-shell">
      <aside
        aria-label={tx("Разделы приложения")}
        className="flex h-full w-64 shrink-0 flex-col border-r border-tg-hint/10 bg-tg-secondary-bg/30"
      >
        <div className="flex items-center gap-2 px-4 pb-3 pt-4">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-tile bg-tg-link/15 text-tg-link">
            <Icon name={manage ? "layout" : "shift"} size={18} />
          </span>
          <div className="min-w-0">
            {/* Заголовок зоны — `h1` каркаса: на десктопе `ManageZone` свою
                шапку не рисует, и без этого у кабинета не было заголовка
                первого уровня вообще. */}
            <h1 className="truncate text-heading text-tg-text">
              {manage ? tx("Управление") : "SemiTask"}
            </h1>
            <div className="truncate text-2xs text-tg-hint">
              {manage ? tx("Кабинет руководителя") : tx("Смена и команда")}
            </div>
          </div>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {manage ? (
            <>
              <section className="mt-2">
                <h2 className="px-3 py-1 text-2xs font-semibold uppercase tracking-wide text-tg-hint">
                  {tx("Работа")}
                </h2>
                <ul className="space-y-1">
                  {adminItems.map((item) => {
                    const active = adminSection === item.id;
                    return (
                      <li key={item.id}>
                        <button
                          type="button"
                          aria-current={active ? "page" : undefined}
                          onClick={() => {
                            if (active) return;
                            haptic("light");
                            setAdminSection(item.id);
                          }}
                          className={[
                            "flex min-h-10 w-full items-center gap-2.5 rounded-tile px-3 text-left text-sm transition-colors",
                            active
                              ? "bg-tg-link/15 font-medium text-tg-link"
                              : "text-tg-text hover:bg-tg-secondary-bg/70",
                          ].join(" ")}
                        >
                          <Icon name={item.icon} size={18} />
                          <span
                            className="min-w-0 flex-1 truncate"
                            title={tx(item.label)}
                          >
                            {tx(item.label)}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
              <section className="mt-2">
                <h2 className="px-3 py-1 text-2xs font-semibold uppercase tracking-wide text-tg-hint">
                  {tx("Сервис")}
                </h2>
                <button
                  type="button"
                  aria-current={
                    adminSection === ADMIN_SETTINGS.id ? "page" : undefined
                  }
                  onClick={() => {
                    haptic("light");
                    setAdminSection(ADMIN_SETTINGS.id);
                  }}
                  className={[
                    "flex min-h-10 w-full items-center gap-2.5 rounded-tile px-3 text-left text-sm transition-colors",
                    adminSection === ADMIN_SETTINGS.id
                      ? "bg-tg-link/15 font-medium text-tg-link"
                      : "text-tg-text hover:bg-tg-secondary-bg/70",
                  ].join(" ")}
                >
                  <Icon name={ADMIN_SETTINGS.icon} size={18} />
                  <span
                    className="min-w-0 flex-1 truncate"
                    title={tx(ADMIN_SETTINGS.label)}
                  >
                    {tx(ADMIN_SETTINGS.label)}
                  </span>
                </button>
              </section>
            </>
          ) : (
            staffGroups.map((group) => (
              <section key={group.title} className="mt-2">
                <h2 className="px-3 py-1 text-2xs font-semibold uppercase tracking-wide text-tg-hint">
                  {group.title}
                </h2>
                <ul className="space-y-1">
                  {group.items.map((item) => {
                    const active = tab === item.id;
                    return (
                      <li key={item.id}>
                        <button
                          type="button"
                          aria-current={active ? "page" : undefined}
                          onClick={() => {
                            if (active) return;
                            haptic("light");
                            setTab(item.id);
                          }}
                          className={[
                            "flex min-h-10 w-full items-center gap-2.5 rounded-tile px-3 text-left text-sm transition-colors",
                            active
                              ? "bg-tg-link/15 font-medium text-tg-link"
                              : "text-tg-text hover:bg-tg-secondary-bg/70",
                          ].join(" ")}
                        >
                          <Icon name={item.icon} size={18} />
                          <span
                            className="min-w-0 flex-1 truncate"
                            title={tx(item.label)}
                          >
                            {tx(item.label)}
                          </span>
                          {item.id === "tasks" && openTasks > 0 && (
                            <span
                              aria-hidden
                              data-testid="desktop-tasks-badge"
                              className="shrink-0 rounded-full bg-tg-link/15 px-1.5 text-2xs font-semibold text-tg-text"
                            >
                              {openTasks > 9 ? "9+" : openTasks}
                            </span>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))
          )}
        </nav>

        {!manage && canManage && (
          <div className="px-3 pb-2">
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setMode("manage");
              }}
              className="flex min-h-10 w-full items-center gap-2.5 rounded-tile bg-tg-link/10 px-3 text-left text-sm font-medium text-tg-link"
            >
              <Icon name="layout" size={18} />
              <span className="min-w-0 flex-1 truncate" title={tx("Управление")}>
                {tx("Управление")}
              </span>
            </button>
          </div>
        )}

        <div className="border-t border-tg-hint/10 px-3 py-3">
          <div className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium text-tg-text">
                {meName}
              </div>
              <div className="truncate text-2xs text-tg-hint">{meHint}</div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <LanguageSwitcher />
              <ThemeSwitcher />
            </div>
          </div>
        </div>
      </aside>

      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        {/* Шире 1360px текст в ленте читать неудобно, а рабочая область должна
            оставаться сеткой, а не растянутой резиной. */}
        <div className="mx-auto flex h-full min-h-0 w-full max-w-[1360px] flex-col">
          {children}
        </div>
      </main>
    </div>
  );
}
