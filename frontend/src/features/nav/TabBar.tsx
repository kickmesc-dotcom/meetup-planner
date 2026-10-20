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

// SemiTaskBot: порядок вкладок = порядок рабочего дня. Сначала задачи и
// чек-лист смены (из-за них сотрудник вообще открывает приложение), затем
// табель («кто когда работает»), события смены — лента с ролевой видимостью.
// «Ссылки» у сотрудника уехали в профиль: шесть подписей — предел полосы.
//
// Нижняя полоса осталась в пять-шесть кнопок: восемь подписей на 360px
// нечитаемы. «График» и «Встречи» НЕ удалены — они открываются из профиля
// (раздел «Все разделы»), поэтому функциональность никуда не пропала.
const BASE_ITEMS: Item[] = [
  { id: "tasks", label: "Задачи", icon: "tasks" },
  { id: "checklist", label: "Смена", icon: "shift" },
  { id: "shifts", label: "Табель", icon: "calendar" },
  { id: "feed", label: "События", icon: "feed" },
  { id: "profile", label: "Профиль", icon: "profile" },
];

// Руководителю важнее команда, чем справочник ссылок: «Ссылки» у него
// остаются в профиле, а на их месте — сводка смены по отделу.
const MANAGER_ITEMS: Item[] = [
  { id: "tasks", label: "Задачи", icon: "tasks" },
  { id: "checklist", label: "Смена", icon: "shift" },
  { id: "shifts", label: "Табель", icon: "calendar" },
  { id: "feed", label: "События", icon: "feed" },
  { id: "team", label: "Команда", icon: "team" },
  { id: "profile", label: "Профиль", icon: "profile" },
];

const ADMIN_ITEM: Item = { id: "admin", label: "Админ", icon: "admin" };

export default function TabBar({
  isAdmin,
  canManage = false,
}: {
  isAdmin: boolean;
  /** Руководитель или прописанный админ — видит сводку по команде. */
  canManage?: boolean;
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
            className={[
              "relative flex-1 min-h-12 flex flex-col items-center justify-center py-2 text-xs transition-colors",
              active ? "text-tg-link" : "text-tg-hint",
            ].join(" ")}
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
            <Icon name={it.icon} size={22} />
            <span className="mt-0.5">{it.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
