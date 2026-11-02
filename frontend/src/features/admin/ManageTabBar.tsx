/**
 * Нижняя полоса зоны управления.
 *
 * Зачем она. В зоне сотрудника полоса есть всегда, а в управлении её не было
 * вовсе: человек попадал в кабинет из переключателя зон и дальше шёл только
 * через общий список разделов — на каждый разворот поручения или приёмки два
 * лишних тапа. Получалось, что «главный экран» у сотрудника есть, а у
 * руководителя нет.
 *
 * Что здесь стоит. Не «все разделы по алфавиту», а то, что руководитель
 * открывает каждый день: состояние смены (что горит), поручения (что поручить)
 * и приёмка (что принять). Самая правая кнопка — настройки, и она единственная
 * залитая: по ней видно, что это не ещё один раздел, а дверь в настройки.
 *
 * Чего здесь нет и почему: язык и тема. Они переехали в «Настройки» —
 * в верхней строке они стояли вплотную к вкладкам зон и читались как третья
 * вкладка (жалоба владельца 02.11.2026).
 */
import { motion } from "framer-motion";
import Icon, { type IconName } from "@/components/Icon";
import { useTx } from "@/i18n";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";

interface Item {
  /** Раздел кабинета; `root` — его собственный список разделов. */
  id: string;
  label: string;
  icon: IconName;
  /** Нужно право управления: приёмка без него бессмысленна. */
  manager?: boolean;
}

const ITEMS: Item[] = [
  { id: "root", label: "Кабинет", icon: "layout" },
  { id: "attention", label: "Внимание", icon: "alert" },
  { id: "admin-tasks", label: "Поручения", icon: "clipboard" },
  { id: "review", label: "Приёмка", icon: "check", manager: true },
];

export default function ManageTabBar({
  canManage = false,
  platform = false,
}: {
  canManage?: boolean;
  platform?: boolean;
}) {
  const { tx } = useTx();
  const section = useUI((s) => s.adminSection);
  const setSection = useUI((s) => s.setAdminSection);

  const items = ITEMS.filter((it) => !it.manager || canManage || platform);
  // Настройки — последняя и отдельная: не раздел кабинета по смыслу, поэтому
  // и не в общем списке.
  const settingsActive = section === "settings";

  const go = (id: string) => {
    if (section === id) return;
    haptic("light");
    setSection(id);
  };

  return (
    <nav
      aria-label={tx("Разделы управления")}
      data-testid="manage-tabbar"
      className="flex items-stretch border-t border-tg-secondary-bg bg-tg-bg/95 backdrop-blur"
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
    >
      {items.map((it) => {
        const active = section === it.id;
        return (
          <button
            key={it.id}
            type="button"
            onClick={() => go(it.id)}
            data-no-press
            aria-current={active ? "page" : undefined}
            data-testid={`manage-tab-${it.id}`}
            className={[
              "press-row relative flex min-h-12 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-0.5 py-1.5 text-2xs leading-tight transition-colors",
              active ? "text-tg-link" : "text-tg-hint",
            ].join(" ")}
          >
            {active && (
              <motion.span
                layoutId="manage-tabbar-active"
                className="absolute inset-x-3 top-0 h-0.5 rounded-full bg-tg-link"
                transition={{ type: "spring", stiffness: 500, damping: 32 }}
              />
            )}
            <Icon name={it.icon} size={20} />
            <span className="w-full truncate text-center">{tx(it.label)}</span>
          </button>
        );
      })}
      <button
        type="button"
        onClick={() => go("settings")}
        data-no-press
        aria-current={settingsActive ? "page" : undefined}
        data-testid="manage-tab-settings"
        className={[
          "press-row relative flex min-h-12 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-0.5 py-1.5 text-2xs leading-tight transition-colors",
          settingsActive ? "text-tg-text" : "text-tg-hint",
        ].join(" ")}
      >
        {/* Главная кнопка настроек: заливка вместо иконки-в-строке. Она же
            отвечает на старую претензию — раньше настройки выглядели как
            декоративный «гаечный ключ», который ничего не делал. */}
        <span
          className={[
            "grid h-7 w-7 place-items-center rounded-full transition-colors",
            settingsActive
              ? "bg-tg-link text-white"
              : "bg-tg-link/15 text-tg-link",
          ].join(" ")}
        >
          <Icon name="settings" size={17} />
        </span>
        <span className="w-full truncate text-center">{tx("Настройки")}</span>
      </button>
    </nav>
  );
}
