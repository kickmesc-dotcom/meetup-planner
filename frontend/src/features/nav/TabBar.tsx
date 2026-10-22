import { motion } from "framer-motion";
import Icon, { type IconName } from "@/components/Icon";
import { useUI, type Tab } from "@/store/ui";
import { haptic } from "@/tg/webapp";

interface Item {
  id: Tab;
  label: string;
  /** VISUAL_AUDIT P1.4: единый SVG-набор вместо эмодзи. */
  icon: IconName;
}

// SemiTaskBot (раунд 5): «События» стоят первыми — туда приложение и
// открывается. Дальше по смыслу: свои задачи, чек-лист смены, табель и
// профиль. «Ссылки» у сотрудника уехали в профиль: шесть подписей — предел
// полосы.
//
// Нижняя полоса осталась в пять-шесть кнопок: восемь подписей на 360px
// нечитаемы. «График» и «Встречи» НЕ удалены — они открываются из профиля
// (раздел «Все разделы»), поэтому функциональность никуда не пропала.
const BASE_ITEMS: Item[] = [
  { id: "feed", label: "События", icon: "feed" },
  { id: "tasks", label: "Задачи", icon: "tasks" },
  { id: "checklist", label: "Смена", icon: "shift" },
  { id: "shifts", label: "Табель", icon: "calendar" },
  { id: "profile", label: "Профиль", icon: "profile" },
];

// Руководителю важнее команда, чем справочник ссылок: «Ссылки» у него
// остаются в профиле, а на их месте — сводка смены по отделу.
const MANAGER_ITEMS: Item[] = [
  { id: "feed", label: "События", icon: "feed" },
  { id: "tasks", label: "Задачи", icon: "tasks" },
  { id: "checklist", label: "Смена", icon: "shift" },
  { id: "shifts", label: "Табель", icon: "calendar" },
  { id: "team", label: "Команда", icon: "team" },
  { id: "profile", label: "Профиль", icon: "profile" },
];

const ADMIN_ITEM: Item = { id: "admin", label: "Админ", icon: "admin" };

export default function TabBar({
  isAdmin,
  canManage = false,
  openTasks = 0,
}: {
  isAdmin: boolean;
  /** Руководитель или прописанный админ — видит сводку по команде. */
  canManage?: boolean;
  /**
   * Открытые поручения для счётчика на «Задачах». Приём из соцсетей: число
   * на разделе видно до перехода, без открытия экрана.
   */
  openTasks?: number;
}) {
  const tab = useUI((s) => s.tab);
  const setTab = useUI((s) => s.setTab);
  const items = [
    ...(canManage ? MANAGER_ITEMS : BASE_ITEMS),
    ...(isAdmin ? [ADMIN_ITEM] : []),
  ];

  return (
    <nav
      className="flex items-stretch border-t border-tg-secondary-bg bg-tg-bg/95 backdrop-blur"
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
    >
      {items.map((it) => {
        const active = tab === it.id;
        return (
          <button
            key={it.id}
            type="button"
            onClick={() => {
              if (active) return;
              haptic("light");
              setTab(it.id);
            }}
            // P3.17: у админа с «Командой» семь вкладок на 360–390 px. При
            // 12 px подписи «Команда»/«События» вылезали за кнопку и обрезались
            // по краям экрана. `text-2xs` + truncate держат семь подписей
            // целиком, а min-w-0 не даёт flex-1 раздуться от длинного слова.
            className={[
              "relative flex min-h-12 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-0.5 py-1.5 text-2xs leading-tight transition-colors",
              active ? "text-tg-link" : "text-tg-hint",
            ].join(" ")}
            aria-label={
              it.id === "tasks" && openTasks > 0
                ? `${it.label}, открытых: ${openTasks}`
                : undefined
            }
          >
            {active && (
              <motion.span
                layoutId="tabbar-active"
                className="absolute inset-x-3 top-0 h-0.5 rounded-full bg-tg-link"
                transition={{ type: "spring", stiffness: 500, damping: 32 }}
              />
            )}
            {/* Иконка декоративная — рядом есть подпись, поэтому её не должно
                быть в дереве доступности (иначе скринридер читает "📅 Календарь"). */}
            <Icon name={it.icon} size={20} />
            <span className="w-full truncate text-center">{it.label}</span>
            {it.id === "tasks" && openTasks > 0 && (
              // Счётчик читается как «Задачи: 3 открытых» через aria-label
              // кнопки; сама цифра декоративная, иначе скринридер прочитает
              // «Задачи 3» без объяснения, что это за 3.
              <span
                aria-hidden
                data-testid="tab-tasks-badge"
                className="absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-tg-link/15 px-1 text-3xs font-semibold text-tg-text"
              >
                {openTasks > 9 ? "9+" : openTasks}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
