import { motion } from "framer-motion";
import Icon, { type IconName } from "@/components/Icon";
import { useT } from "@/i18n";
import type { MessageKey } from "@/i18n/messages";
import { useUI, type Tab } from "@/store/ui";
import { sectionEnabled } from "@/features/hr/sections";
import { haptic } from "@/tg/webapp";
import { useTerms } from "@/api/texts";

interface Item {
  id: Tab;
  /** Подпись — ключ словаря: язык переключается без перезагрузки. */
  labelKey: MessageKey;
  /** VISUAL_AUDIT P1.4: единый SVG-набор вместо эмодзи. */
  icon: IconName;
  /**
   * Термин отрасли (B2B_PLATFORM_PLAN, 3.1): у салона не «Смена», а «Приём»,
   * у розницы не «Задачи», а «Заявки». Подставляется поверх перевода, поэтому
   * язык и отрасль не спорят друг с другом: без правки остаётся обычная подпись.
   */
  termCode?: string;
}

// SemiTaskBot (раунд 5): «События» стоят первыми — туда приложение и
// открывается. Дальше по смыслу: свои задачи, чек-лист смены, табель и
// профиль. «Ссылки» у сотрудника уехали в профиль: шесть подписей — предел
// полосы.
//
// 02.11.2026: набор один для всех. Раньше у руководителя вместо «Профиля»
// стояла «Команда», и полоса менялась в зависимости от роли — то есть одна и та
// же зона выглядела по-разному у разных людей. Теперь это полоса сотрудника в
// буквальном смысле: руководитель видит здесь ровно то же, что и его люди, а
// команда, приёмка и отчёт живут в зоне управления (вкладки вверху экрана).
const ITEMS: Item[] = [
  { id: "feed", labelKey: "nav.feed", icon: "feed" },
  { id: "tasks", labelKey: "nav.tasks", icon: "tasks", termCode: "task.many" },
  { id: "checklist", labelKey: "nav.shift", icon: "shift", termCode: "shift.one" },
  { id: "shifts", labelKey: "nav.table", icon: "calendar" },
  { id: "profile", labelKey: "nav.profile", icon: "profile" },
];

export default function TabBar({
  sections,
  openTasks = 0,
}: {
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
  const term = useTerms();
  // «Управление» (админка) из нижней полосы убрано 31.10.2026. Причина не в
  // дизайне, а в разделении ролей: полоса — это рабочий день сотрудника, а
  // кабинет предприятия — отдельный блок руководителя. Семь подписей на
  // 360–390 px уже обрезались, а сотрудник видел вкладку, которая ему не
  // принадлежит: достаточно было попасть в ADMIN_TG_IDS, чтобы она появилась.
  // Вход в кабинет теперь один и осознанный — из профиля, раздел
  // «Руководителю» (см. `HrProfileScreen`), и только у того, кому сервер это
  // разрешил.
  const items = ITEMS.filter(
    (item) => !sections || sectionEnabled(item.id, sections),
  );

  return (
    <nav
      className="flex items-stretch border-t border-tg-secondary-bg bg-tg-bg/95 backdrop-blur"
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
    >
      {items.map((it) => {
        const active = tab === it.id;
        const label = it.termCode ? term(it.termCode, t(it.labelKey)) : t(it.labelKey);
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
