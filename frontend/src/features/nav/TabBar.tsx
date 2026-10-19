import { motion } from "framer-motion";
import { useUI, type Tab } from "@/store/ui";
import { haptic } from "@/tg/webapp";

interface Item {
  id: Tab;
  label: string;
  icon: string;
}

// SemiTaskBot: порядок вкладок = порядок рабочего дня. Сначала задачи и
// чек-лист смены (из-за них сотрудник вообще открывает приложение), затем
// табель («кто когда работает»), события смены — лента с ролевой видимостью.
// «Ссылки» у сотрудника уехали в профиль: шесть подписей — предел полосы.
//
// Нижняя полоса осталась в пять-шесть кнопок: восемь подписей на 360px
// нечитаемы. «График» и «Встречи» НЕ удалены — они открываются из профиля
// (раздел «Быстрые переходы»), поэтому функциональность никуда не пропала.
const BASE_ITEMS: Item[] = [
  { id: "tasks", label: "Задачи", icon: "✅" },
  { id: "checklist", label: "Смена", icon: "🕒" },
  { id: "shifts", label: "Табель", icon: "🗓" },
  { id: "feed", label: "События", icon: "📋" },
  { id: "profile", label: "Профиль", icon: "👤" },
];

// Руководителю важнее команда, чем справочник ссылок: «Ссылки» у него
// остаются в профиле, а на их месте — сводка смены по отделу.
const MANAGER_ITEMS: Item[] = [
  { id: "tasks", label: "Задачи", icon: "✅" },
  { id: "checklist", label: "Смена", icon: "🕒" },
  { id: "shifts", label: "Табель", icon: "🗓" },
  { id: "feed", label: "События", icon: "📋" },
  { id: "team", label: "Команда", icon: "👀" },
  { id: "profile", label: "Профиль", icon: "👤" },
];

const ADMIN_ITEM: Item = { id: "admin", label: "Админ", icon: "⚙️" };

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
              "relative flex-1 min-h-12 flex flex-col items-center justify-center py-2 text-[11px] transition-colors",
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
            <span className="text-lg leading-none" aria-hidden>
              {it.icon}
            </span>
            <span className="mt-0.5">{it.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
