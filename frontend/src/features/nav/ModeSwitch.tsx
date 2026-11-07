import { motion } from "framer-motion";
import Icon, { type IconName } from "@/components/Icon";
import { useTx } from "@/i18n";
import { useUI, type AppMode } from "@/store/ui";
import { haptic } from "@/tg/webapp";

/**
 * Верхний переключатель зон: «Сотрудник | Управление».
 *
 * Зачем он появился. До 02.11.2026 разделение было половинчатым: у руководителя
 * менялся состав нижней полосы (вместо «Профиля» — «Команда»), а кабинет
 * открывался строкой в профиле. Две зоны выглядели как одна зона с разными
 * кнопками, и человек не понимал, где кончается его работа и начинается работа
 * руководителя.
 *
 * Теперь граница видна сразу и она одна: две вкладки вверху экрана.
 * Сотрудник этот компонент не рисует вовсе — у него одна зона и вкладок нет
 * (см. `App.tsx`, флаг `canManageZone`). Права — не забота переключателя: он
 * показывает ровно то состояние, что лежит в сторе, и ничего не решает сам.
 */
interface Zone {
  id: AppMode;
  label: string;
  icon: IconName;
}

const ZONES: Zone[] = [
  { id: "staff", label: "Сотрудник", icon: "shift" },
  { id: "manage", label: "Управление", icon: "admin" },
];

export default function ModeSwitch({ className }: { className?: string }) {
  const { tx } = useTx();
  const mode = useUI((s) => s.mode);
  const setMode = useUI((s) => s.setMode);

  return (
    <div
      role="tablist"
      aria-label={tx("Зона приложения")}
      data-testid="mode-switch"
      className={[
        "flex items-center gap-1 rounded-full bg-tg-secondary-bg/80 p-1",
        className ?? "",
      ].join(" ")}
    >
      {ZONES.map((zone) => {
        const active = mode === zone.id;
        return (
          <button
            key={zone.id}
            type="button"
            role="tab"
            aria-selected={active}
            data-testid={`mode-${zone.id}`}
            onClick={() => {
              if (active) return;
              haptic("selection");
              setMode(zone.id);
            }}
            className={[
              "relative flex min-h-9 flex-1 items-center justify-center gap-1.5 rounded-full px-3 text-xs transition-colors",
              active ? "font-semibold text-tg-text" : "text-tg-hint",
            ].join(" ")}
          >
            {active && (
              <motion.span
                layoutId="mode-switch-active"
                className="absolute inset-0 rounded-full bg-tg-bg shadow-raised"
                transition={{ type: "spring", stiffness: 500, damping: 34 }}
              />
            )}
            {/* Иконка декоративная: подпись рядом, и скринридер не должен
                читать её отдельным словом. */}
            <span className="relative flex items-center gap-1.5">
              <Icon name={zone.icon} size={15} />
              <span className="whitespace-nowrap">{tx(zone.label)}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
