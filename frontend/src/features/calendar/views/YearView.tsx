import { useMemo } from "react";
import { isSameMonth, isToday, startOfMonth } from "date-fns";
import type { AvailabilityRange, User } from "@/types";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";
import {
  buildMonthGrid,
  ruMonthFull,
  summarizeDay,
} from "../dateUtils";

interface Props {
  anchor: Date;
  ranges: AvailabilityRange[];
  users: User[];
}

export default function YearView({ anchor, ranges, users }: Props) {
  const setZoom = useUI((s) => s.setZoom);
  const setAnchor = useUI((s) => s.setAnchorDate);

  const months = useMemo(
    () =>
      Array.from({ length: 12 }, (_, m) => startOfMonth(new Date(anchor.getFullYear(), m, 1))),
    [anchor],
  );

  const onMonthTap = (m: Date) => {
    haptic("light");
    setAnchor(m);
    setZoom("month");
  };

  return (
    <div className="flex-1 overflow-y-auto p-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {months.map((m) => (
          <button
            key={m.getMonth()}
            type="button"
            onClick={() => onMonthTap(m)}
            className="bg-tg-secondary-bg/40 rounded-2xl p-2 text-left active:scale-95 transition-transform"
          >
            <div className="text-xs font-semibold mb-1 capitalize">
              {ruMonthFull(m.getMonth())}
            </div>
            <MiniMonth monthAnchor={m} ranges={ranges} users={users} />
          </button>
        ))}
      </div>
    </div>
  );
}

function MiniMonth({
  monthAnchor,
  ranges,
  users,
}: {
  monthAnchor: Date;
  ranges: AvailabilityRange[];
  users: User[];
}) {
  const grid = useMemo(() => buildMonthGrid(monthAnchor), [monthAnchor]);
  const total = users.length || 6;
  return (
    <div className="grid grid-cols-7 gap-px">
      {grid.map((d) => {
        const inMonth = isSameMonth(d, monthAnchor);
        const today = isToday(d);
        const sum = summarizeDay(d, ranges);
        const ratio = total > 0 ? sum.free / total : 0;
        const bg =
          ratio >= 0.66
            ? "bg-status-free"
            : ratio >= 0.34
              ? "bg-status-free/50"
              : ratio > 0
                ? "bg-status-free/25"
                : "bg-transparent";
        return (
          <div
            key={d.toISOString()}
            className={[
              "aspect-square rounded-[3px] flex items-center justify-center text-[8px]",
              inMonth ? "text-tg-text" : "text-tg-hint/40",
              today ? "ring-1 ring-tg-link" : "",
              bg,
            ].join(" ")}
          >
            {d.getDate()}
          </div>
        );
      })}
    </div>
  );
}
