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
              // `min-w-0` + перенос подписи: при 200 % системного шрифта
              // «Управление» шире своей половины контрола, и без переноса
              // контрол выпихивал шапку за правый край (§1.4.4).
              // §1.4.5 `touch-target-size`: 36 px было ниже минимума 44 px,
              // и переключатель зон — первое, что человек трогает в шапке.
              "relative flex min-h-11 min-w-0 flex-1 items-center justify-center gap-1.5 rounded-full px-2 py-1 text-center text-xs leading-tight transition-colors",
              // Неактивная зона — `text-tg-hint` на `secondary-bg/80`:
              // axe дал ниже AA. Цвет текста одинаковый, состояние читается
              // по подложке и весу — как у сегмент-контрола iOS.
              active ? "font-semibold text-tg-text" : "text-tg-text/90",
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
            <span className="relative flex min-w-0 items-center gap-1.5">
              <Icon name={zone.icon} size={15} />
              {/* Без `whitespace-nowrap`: слово переносится, но не обрезается.
                  Обрезка была бы потерей содержимого, а не компактностью. */}
              <span className="min-w-0 break-words">{tx(zone.label)}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
