import { motion } from "framer-motion";
import { useUI, type Tab } from "@/store/ui";
import { haptic } from "@/tg/webapp";

interface Item {
  id: Tab;
  label: string;
  icon: string;
}

const BASE_ITEMS: Item[] = [
  { id: "calendar", label: "Календарь", icon: "📅" },
  { id: "meetings", label: "Встречи", icon: "🤝" },
  { id: "polls", label: "Опросы", icon: "🗳️" },
  // GHG8 P4.1.d: «Топы» → «Профиль» (топы и история — внутри).
  { id: "profile", label: "Профиль", icon: "👤" },
];

const ADMIN_ITEM: Item = { id: "admin", label: "Админ", icon: "⚙️" };

export default function TabBar({ isAdmin }: { isAdmin: boolean }) {
  const tab = useUI((s) => s.tab);
  const setTab = useUI((s) => s.setTab);
  const items = isAdmin ? [...BASE_ITEMS, ADMIN_ITEM] : BASE_ITEMS;

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
            <span className="text-lg leading-none">{it.icon}</span>
            <span className="mt-0.5">{it.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
