import { motion } from "framer-motion";
import Icon, { type IconName } from "@/components/Icon";
import { useT } from "@/i18n";
import type { MessageKey } from "@/i18n/messages";
import { useUI, type Tab } from "@/store/ui";
import { sectionEnabled } from "@/features/hr/sections";
import { haptic } from "@/tg/webapp";

interface Item {
  id: Tab;
  /** Подпись — ключ словаря: язык переключается без перезагрузки. */
  labelKey: MessageKey;
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
  { id: "feed", labelKey: "nav.feed", icon: "feed" },
  { id: "tasks", labelKey: "nav.tasks", icon: "tasks" },
  { id: "checklist", labelKey: "nav.shift", icon: "shift" },
  { id: "shifts", labelKey: "nav.table", icon: "calendar" },
  { id: "profile", labelKey: "nav.profile", icon: "profile" },
];

// Руководителю важнее команда, чем справочник ссылок: «Ссылки» у него
// остаются в профиле, а на их месте — сводка смены по отделу.
const MANAGER_ITEMS: Item[] = [
  { id: "feed", labelKey: "nav.feed", icon: "feed" },
  { id: "tasks", labelKey: "nav.tasks", icon: "tasks" },
  { id: "checklist", labelKey: "nav.shift", icon: "shift" },
  { id: "shifts", labelKey: "nav.table", icon: "calendar" },
  { id: "team", labelKey: "nav.team", icon: "team" },
  { id: "profile", labelKey: "nav.profile", icon: "profile" },
];

const ADMIN_ITEM: Item = { id: "admin", labelKey: "nav.admin", icon: "admin" };

export default function TabBar({
  isAdmin,
  canManage = false,
  sections,
  openTasks = 0,
}: {
  isAdmin: boolean;
  /** Руководитель или прописанный админ — видит сводку по команде. */
  canManage?: boolean;
  /** Разделы из настройки организации (undefined — ничего не прячем). */
  sections?: string[];
  /**
   * Открытые поручения для счётчика на «Задачах». Приём из соцсетей: число
   * на разделе видно до перехода, без открытия экрана.
   */
  openTasks?: number;
}) {
  const tab = useUI((s) => s.tab);
  const setTab = useUI((s) => s.setTab);
  const { t } = useT();
  const items = [
    ...(canManage ? MANAGER_ITEMS : BASE_ITEMS),
    ...(isAdmin ? [ADMIN_ITEM] : []),
  ].filter((item) => !sections || sectionEnabled(item.id, sections));

  return (
    <nav
      className="flex items-stretch border-t border-tg-secondary-bg bg-tg-bg/95 backdrop-blur"
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
    >
      {items.map((it) => {
        const active = tab === it.id;
        const label = t(it.labelKey);
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
            // §10: вкладку не сжимаем — она занимает всю высоту полосы, и
            // сжатие читалось бы как «прыжок» полосы. Вместо этого подсветка
            // (как в iOS): палец нажал — вкладка тихо потемнела.
            data-no-press
            className={[
              "press-row relative flex min-h-12 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-0.5 py-1.5 text-2xs leading-tight transition-colors",
              active ? "text-tg-link" : "text-tg-hint",
            ].join(" ")}
            aria-label={
              it.id === "tasks" && openTasks > 0
                ? t("nav.tasksOpen", { label, count: openTasks })
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
            <span className="w-full truncate text-center">{label}</span>
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
