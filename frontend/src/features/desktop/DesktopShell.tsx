import type { ReactNode } from "react";
import Icon, { type IconName } from "@/components/Icon";
import LanguageSwitcher from "@/components/LanguageSwitcher";
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
 * эта оболочка — постоянный сайдбар со всеми разделами и широкая рабочая
 * область. Причина простая: в нижнюю полосу влезает пять-шесть подписей, а на
 * 1440px это выглядит как телефон, растянутый на монитор, и половина экрана
 * пустует.
 *
 * Группы разделов повторяют логику работы, а не порядок вкладок: «Смена» — что
 * делать сейчас, «Команда» — что с людьми (там же приёмка и отчёты), «Сервис» —
 * календарь, встречи и справочники. Пункт показывается только если у человека
 * есть на него право — ровно как в нижней полосе.
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

const WORK: NavItem[] = [
  { id: "feed", label: "События", icon: "feed" },
  { id: "tasks", label: "Мои задачи", icon: "tasks" },
  { id: "checklist", label: "Чек-лист смены", icon: "clipboard" },
  { id: "shifts", label: "Табель", icon: "calendar" },
  { id: "materials", label: "Материалы", icon: "book" },
];

const SERVICE: NavItem[] = [
  { id: "calendar", label: "Календарь", icon: "calendar" },
  { id: "meetings", label: "Встречи и опросы", icon: "clock" },
  { id: "standards", label: "Стандарты", icon: "checklist" },
  { id: "links", label: "Ссылки", icon: "globe" },
];

const PROFILE: NavItem = { id: "profile", label: "Профиль", icon: "profile" };

export default function DesktopShell({
  canManage,
  isAdmin,
  meName,
  meHint,
  openTasks = 0,
  sections,
  children,
}: {
  /** Руководитель или прописанный админ: видны «Команда», приёмка и отчёты. */
  canManage: boolean;
  /** Разделы из настройки организации (undefined — ничего не прячем). */
  sections?: string[];
  /** Полный админ — виден раздел «Управление». */
  isAdmin: boolean;
  meName: string;
  meHint: string;
  /** Открытые поручения — счётчик рядом с «Мои задачи», как в соцсетях. */
  openTasks?: number;
  children: ReactNode;
}) {
  const { tx } = useTx();
  const tab = useUI((s) => s.tab);
  const setTab = useUI((s) => s.setTab);

  const team: NavItem[] = [
    ...(canManage
      ? ([
          { id: "team", label: "Команда", icon: "team" },
          { id: "review", label: "Приёмка работ", icon: "checklist" },
          { id: "reports", label: "Отчёт смены", icon: "layout" },
        ] satisfies NavItem[])
      : []),
    { id: "issues", label: "Проблемы", icon: "alert" },
    { id: "handovers", label: "Передачи смены", icon: "repeat" },
  ];

  const keep = (items: NavItem[]) =>
    sections ? items.filter((item) => sectionEnabled(item.id, sections)) : items;
  const groups: NavGroup[] = [
    { title: tx("Смена"), items: keep(WORK) },
    { title: tx("Команда"), items: keep(team) },
    { title: tx("Сервис"), items: keep([...SERVICE, PROFILE]) },
    ...(isAdmin
      ? [
          {
            title: tx("Управление"),
            items: [
              {
                id: "admin" as Tab,
                label: tx("Админка"),
                icon: "admin" as IconName,
              },
            ],
          },
        ]
      : []),
  ];

  return (
    <div className="flex h-full min-h-0 w-full" data-testid="desktop-shell">
      <aside
        aria-label={tx("Разделы приложения")}
        className="flex h-full w-64 shrink-0 flex-col border-r border-tg-hint/10 bg-tg-secondary-bg/30"
      >
        <div className="flex items-center gap-2 px-4 pb-3 pt-4">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-tile bg-tg-link/15 text-tg-link">
            <Icon name="shift" size={18} />
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-tg-text">
              SemiTask
            </div>
            <div className="truncate text-2xs text-tg-hint">
              {tx("Смена и команда")}
            </div>
          </div>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {groups.map((group) => (
            <section key={group.title} className="mt-2">
              <h2 className="px-3 py-1 text-2xs font-semibold uppercase tracking-wide text-tg-hint">
                {group.title}
              </h2>
              <ul className="space-y-0.5">
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
                        <span className="min-w-0 flex-1 truncate">
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
          ))}
        </nav>

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
