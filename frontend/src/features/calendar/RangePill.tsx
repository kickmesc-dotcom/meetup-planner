import { motion } from "framer-motion";
import type { AvailabilityRange } from "@/types";
import { PillRect, statusColor, statusLabel, statusLabelShort } from "./dateUtils";

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
      className="absolute top-1/2 -translate-y-1/2 h-7 px-2 text-white text-[11px] font-medium flex items-center shadow-sm select-none"
      style={{
        left,
        width,
        background: statusColor(range.status),
        opacity: range.confidence >= 4 ? 0.7 : 1,
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
