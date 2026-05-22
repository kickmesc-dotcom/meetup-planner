import { motion } from "framer-motion";
import { useUI, type ZoomLevel } from "@/store/ui";
import { haptic } from "@/tg/webapp";

/**
 * GHG6 P3 CL13 + CL6.b + CL5: нижняя плашка управления для TimelineView.
 *
 * Содержит:
 *  - стрелки ←/→ — shiftAnchor вперёд/назад на единицу текущего zoom;
 *  - 5 пресет-кнопок: День / Неделя / Месяц / Год / Все года.
 *    Первые три остаются внутри TimelineView и заодно подменяют cellWidth
 *    через `timelineCellWidth` (CL5). Год/Все года переключают на legacy
 *    YearView/AllYearsView (см. CalendarView.useTimelineForCurrentZoom);
 *  - слайдер зума (CL5) — cellWidth ∈ [24, 120]px;
 *  - кнопка «📍 К сегодня» (CL6.b).
 */

const CELL_WIDTH_MIN = 24;
const CELL_WIDTH_MAX = 120;

/**
 * Соотношение pixel-per-day для каждого «timeline-режима». При выборе пресета
 * мы кладём это значение в `timelineCellWidth`, а ResizeObserver TimelineView
 * перестаёт перебивать. Сброс к auto (null) — двойной тап по уже-активной кнопке.
 */
const PRESET_CELL_WIDTH: Record<"day" | "week" | "month", number> = {
  day: 120, // 1 день занимает ~viewport
  week: 56, // 7 дней в ширине (примерно)
  month: 28, // ~30 дней
};

const PRESETS: Array<{ z: ZoomLevel; label: string }> = [
  { z: "day", label: "День" },
  { z: "week", label: "Неделя" },
  { z: "month", label: "Месяц" },
  { z: "year", label: "Год" },
  { z: "allYears", label: "Все года" },
];

interface Props {
  /** Если true, кнопка «К сегодня» подсвечена-disabled (anchor уже сегодня). */
  isOnToday: boolean;
}

export default function TimelineNavBar({ isOnToday }: Props) {
  const zoom = useUI((s) => s.zoom);
  const setZoom = useUI((s) => s.setZoom);
  const shift = useUI((s) => s.shiftAnchor);
  const goToday = useUI((s) => s.goToday);
  const cellWidth = useUI((s) => s.timelineCellWidth);
  const setCellWidth = useUI((s) => s.setTimelineCellWidth);

  const onPreset = (z: ZoomLevel) => {
    haptic("selection");
    setZoom(z);
    if (z === "day" || z === "week" || z === "month") {
      setCellWidth(PRESET_CELL_WIDTH[z]);
    } else {
      // Год / Все года — TimelineView не рендерится, cellWidth не используется.
      setCellWidth(null);
    }
  };

  // Активный пресет (по zoom). cellWidth не учитываем здесь — пользователь
  // мог двинуть слайдер вручную, и это нормально.
  const isTimelineMode = zoom === "day" || zoom === "week" || zoom === "month";

  return (
    <div
      className="border-t border-tg-secondary-bg/80 bg-tg-bg px-2 py-2 flex flex-col gap-2"
      role="toolbar"
      aria-label="Управление календарём"
    >
      <div className="flex items-center gap-2">
        <NavBtn
          onClick={() => {
            haptic("light");
            shift(-1);
          }}
          label="←"
          aria="Назад"
        />
        <div className="flex-1 grid grid-cols-5 gap-1">
          {PRESETS.map((p) => {
            const active = zoom === p.z;
            return (
              <button
                key={p.z}
                type="button"
                onClick={() => onPreset(p.z)}
                className={[
                  "min-h-9 rounded-md text-[12px] font-medium px-1 py-1 active:scale-[0.97] transition-transform",
                  active
                    ? "bg-tg-button text-tg-button-text shadow-sm"
                    : "bg-tg-secondary-bg text-tg-text",
                ].join(" ")}
              >
                {p.label}
              </button>
            );
          })}
        </div>
        <NavBtn
          onClick={() => {
            haptic("light");
            shift(1);
          }}
          label="→"
          aria="Вперёд"
        />
      </div>

      {/* CL5: слайдер зума доступен только когда TimelineView активен. На
          Год/Все года он бесполезен — там cellWidth не используется. */}
      {isTimelineMode && (
        <div className="flex items-center gap-2 px-1">
          <span className="text-[10px] text-tg-hint min-w-6 text-right tabular-nums">
            {Math.round(cellWidth ?? 56)}px
          </span>
          <input
            type="range"
            min={CELL_WIDTH_MIN}
            max={CELL_WIDTH_MAX}
            step={1}
            value={cellWidth ?? 56}
            onChange={(e) => {
              setCellWidth(Number(e.target.value));
            }}
            onPointerUp={() => haptic("light")}
            className="flex-1 accent-tg-link"
            aria-label="Зум таймлайна"
          />
          <button
            type="button"
            onClick={() => {
              haptic("selection");
              setCellWidth(null);
            }}
            className="text-[10px] text-tg-link active:opacity-70"
            title="Авто-ширина по контейнеру"
          >
            авто
          </button>
        </div>
      )}

      <div className="flex justify-center">
        <motion.button
          type="button"
          onClick={() => {
            haptic("selection");
            goToday();
          }}
          disabled={isOnToday}
          whileTap={{ scale: 0.96 }}
          className={[
            "rounded-full px-3 py-1.5 text-xs font-medium inline-flex items-center gap-1",
            isOnToday
              ? "bg-tg-secondary-bg/40 text-tg-hint"
              : "bg-tg-secondary-bg text-tg-text active:bg-tg-button/30",
          ].join(" ")}
        >
          📍 К сегодня
        </motion.button>
      </div>
    </div>
  );
}

function NavBtn({
  onClick,
  label,
  aria,
}: {
  onClick: () => void;
  label: string;
  aria: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={aria}
      className="min-w-9 min-h-9 rounded-md bg-tg-secondary-bg text-tg-text font-semibold active:scale-[0.96] transition-transform"
    >
      {label}
    </button>
  );
}
