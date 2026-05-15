import { useMemo } from "react";
import { addMonths, isSameMonth, isToday, startOfMonth } from "date-fns";
import type { AvailabilityRange, User } from "@/types";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";
import {
  buildMonthGrid,
  ruMonthFull,
  ruWeekdayShort,
  summarizeDay,
} from "../dateUtils";

interface Props {
  /** Сколько подряд месяцев показать. month=1, threeMonths=3, sixMonths=6. */
  months: number;
  anchor: Date;
  ranges: AvailabilityRange[];
  users: User[];
}

export default function MonthView({ months, anchor, ranges, users }: Props) {
  const setZoom = useUI((s) => s.setZoom);
  const setAnchor = useUI((s) => s.setAnchorDate);

  const monthAnchors = useMemo(() => {
    // Для threeMonths/sixMonths центрируем вокруг anchor.
    const offset = -Math.floor((months - 1) / 2);
    return Array.from({ length: months }, (_, i) =>
      startOfMonth(addMonths(anchor, offset + i)),
    );
  }, [months, anchor]);

  const onDayTap = (d: Date) => {
    haptic("light");
    setAnchor(d);
    setZoom("day");
  };

  return (
    <div className="flex-1 overflow-y-auto pb-4">
      {monthAnchors.map((m) => (
        <MonthBlock
          key={m.toISOString()}
          monthAnchor={m}
          ranges={ranges}
          users={users}
          onDayTap={onDayTap}
        />
      ))}
    </div>
  );
}

function MonthBlock({
  monthAnchor,
  ranges,
  users,
  onDayTap,
}: {
  monthAnchor: Date;
  ranges: AvailabilityRange[];
  users: User[];
  onDayTap: (d: Date) => void;
}) {
  const grid = useMemo(() => buildMonthGrid(monthAnchor), [monthAnchor]);
  const totalUsers = users.length || 6;

  return (
    <div className="px-3 mb-4">
      <div className="text-base font-semibold mb-2">
        {ruMonthFull(monthAnchor.getMonth())} {monthAnchor.getFullYear()}
      </div>
      <div className="grid grid-cols-7 gap-px text-[10px] text-tg-hint mb-1">
        {[1, 2, 3, 4, 5, 6, 0].map((d) => (
          <div key={d} className="text-center uppercase">
            {ruWeekdayShort(d)}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {grid.map((d) => {
          const inMonth = isSameMonth(d, monthAnchor);
          const today = isToday(d);
          const sum = summarizeDay(d, ranges);
          const unmarked = Math.max(0, totalUsers - sum.total);
          // Логика «не размечено = занят»: считаем эффективно занятыми всех
          // не отметившихся. Фон — по плотности реально свободных.
          const effectiveBusy = sum.busy + unmarked;
          const ratioFree = totalUsers > 0 ? sum.free / totalUsers : 0;
          const ratioMaybe = totalUsers > 0 ? sum.maybe / totalUsers : 0;
          const ratioBusy = totalUsers > 0 ? effectiveBusy / totalUsers : 0;
          const bg =
            ratioFree >= 0.66
              ? "bg-status-free/30"
              : ratioFree >= 0.34
                ? "bg-status-free/15"
                : ratioMaybe >= 0.34
                  ? "bg-status-maybe/15"
                  : ratioBusy >= 0.66
                    ? "bg-status-busy/15"
                    : "bg-tg-secondary-bg/40";
          return (
            <button
              key={d.toISOString()}
              type="button"
              onClick={() => onDayTap(d)}
              className={[
                "aspect-square rounded-lg flex flex-col items-center justify-start py-1 px-1 text-xs transition-transform active:scale-95 relative",
                inMonth ? "text-tg-text" : "text-tg-hint/60",
                today ? "ring-2 ring-tg-link" : "",
                bg,
              ].join(" ")}
            >
              <span className={today ? "font-bold" : "font-medium"}>{d.getDate()}</span>
              <div className="flex gap-0.5 mt-auto pb-0.5">
                {Array.from({ length: Math.min(sum.free, 3) }).map((_, i) => (
                  <span key={`f${i}`} className="w-1 h-1 rounded-full bg-status-free" />
                ))}
                {Array.from({ length: Math.min(sum.maybe, 3) }).map((_, i) => (
                  <span key={`m${i}`} className="w-1 h-1 rounded-full bg-status-maybe" />
                ))}
                {Array.from({ length: Math.min(effectiveBusy, 3) }).map((_, i) => (
                  <span key={`b${i}`} className="w-1 h-1 rounded-full bg-status-busy" />
                ))}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
