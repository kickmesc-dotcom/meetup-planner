import { motion } from "framer-motion";
import type { AvailabilityRange } from "@/types";
import { PillRect, statusPillBg, statusLabel, statusLabelShort } from "./dateUtils";

interface Props {
  range: AvailabilityRange;
  rect: PillRect;
  windowSpan: number;
  isOwn: boolean;
  onTap: () => void;
}

/**
 * Inline range indicator. Drag/resize отключены (правило «1 ячейка = 1 день»):
 * новые диапазоны создаются тапом по пустой ячейке, редактирование границ —
 * через bottom-sheet редактор. Существующие multi-day диапазоны из БД
 * по-прежнему рендерятся как непрерывная полоса.
 */
export default function RangePill({
  range,
  rect,
  windowSpan,
  isOwn,
  onTap,
}: Props) {
  const left = `calc(${(rect.startIndex / windowSpan) * 100}% + 2px)`;
  const width = `calc(${(rect.span / windowSpan) * 100}% - 4px)`;
  const radiusL = rect.clippedLeft ? 4 : 999;
  const radiusR = rect.clippedRight ? 4 : 999;

  const now = Date.now();
  const isCurrent =
    new Date(range.starts_at).getTime() <= now &&
    new Date(range.ends_at).getTime() > now;

  return (
    <motion.div
      layout
      initial={{ scale: 0.9, opacity: 0 }}
      animate={
        isCurrent
          ? {
              scale: 1,
              opacity: 1,
              boxShadow: [
                "0 0 0 0 rgba(255,255,255,0.0)",
                "0 0 0 4px rgba(255,255,255,0.55)",
                "0 0 0 0 rgba(255,255,255,0.0)",
              ],
            }
          : { scale: 1, opacity: 1 }
      }
      exit={{ scale: 0.85, opacity: 0 }}
      transition={
        isCurrent
          ? { boxShadow: { repeat: Infinity, duration: 1.6 } }
          : { type: "spring", damping: 28, stiffness: 360 }
      }
      onClick={(e) => {
        e.stopPropagation();
        onTap();
      }}
      // Плашка была `div` с `onClick`: мышью открывалась, с клавиатуры — нет.
      // Теперь это кнопка по смыслу: Enter/Space открывают тот же редактор,
      // где границы и статус меняются обычными кнопками. Это и есть
      // клавиатурная альтернатива перетаскиванию (§2.5.7
      // `dragging-alternative`): жест ничего не добавляет, чего нельзя
      // сделать из редактора.
      role="button"
      tabIndex={0}
      aria-label={`${range.note ?? statusLabel(range.status)}, ${statusLabelShort(range.status)}`}
      onKeyDown={(e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        onTap();
      }}
      className="absolute top-1/2 -translate-y-1/2 h-7 px-2 text-white text-xs font-medium flex items-center shadow-raised select-none"
      style={{
        left,
        width,
        // DESIGN_SYSTEM §1.2/§6: darkened pill bg + white text = WCAG AA at 12px.
        // Confidence is already encoded by the cell fill, so we no longer fade the
        // pill (the old opacity<1 pushed the label below AA contrast).
        background: statusPillBg(range.status),
        borderTopLeftRadius: radiusL,
        borderBottomLeftRadius: radiusL,
        borderTopRightRadius: radiusR,
        borderBottomRightRadius: radiusR,
        cursor: isOwn ? "pointer" : "default",
      }}
      title={range.note ?? statusLabel(range.status)}
    >
      <span className="truncate flex-1">
        {range.note ?? (rect.span <= 1 ? statusLabelShort(range.status) : statusLabel(range.status))}
      </span>
    </motion.div>
  );
}
