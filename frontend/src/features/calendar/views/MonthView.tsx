import { useMemo } from "react";
import { addMonths, format, isSameMonth, isToday, startOfMonth } from "date-fns";
import type { AvailabilityRange, User } from "@/types";
import type { BirthdayCalendarEntry } from "@/api/birthdays";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";
import {
  buildMonthGrid,
  ruMonthFull,
  ruWeekdayShort,
  summarizeDay,
} from "../dateUtils";

// GHG6 BD1: в MonthView нет «строк по участникам», но иконка 🎂 должна
// открывать поповер, а не только проваливать тап на день. Это ближайшая
// аппроксимация спецификации в рамках сетки.

interface Props {
  /** Сколько подряд месяцев показать. month=1, threeMonths=3, sixMonths=6. */
  months: number;
  anchor: Date;
  ranges: AvailabilityRange[];
  users: User[];
  birthdays?: BirthdayCalendarEntry[];
}

export default function MonthView({ months, anchor, ranges, users, birthdays = [] }: Props) {
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

  // Индекс ДР: ключ — YYYY-MM-DD, значение — список именинников (id+имя).
  // Берём первого для дефолтного клика — поповер открывается на нём.
  const bdayIndex = useMemo(() => {
    const idx = new Map<string, BirthdayCalendarEntry[]>();
    for (const b of birthdays) {
      const arr = idx.get(b.date) ?? [];
      arr.push(b);
      idx.set(b.date, arr);
    }
    return idx;
  }, [birthdays]);

  return (
    <div className="flex-1 overflow-y-auto pb-4">
      {monthAnchors.map((m) => (
        <MonthBlock
          key={m.toISOString()}
          monthAnchor={m}
          ranges={ranges}
          users={users}
          bdayIndex={bdayIndex}
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
  bdayIndex,
  onDayTap,
}: {
  monthAnchor: Date;
  ranges: AvailabilityRange[];
  users: User[];
  bdayIndex: Map<string, BirthdayCalendarEntry[]>;
  onDayTap: (d: Date) => void;
}) {
  const setBirthdayPopover = useUI((s) => s.setBirthdayPopover);
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
          const dayKey = format(d, "yyyy-MM-dd");
          const bdayList = bdayIndex.get(dayKey);
          return (
            <button
              key={d.toISOString()}
              type="button"
              onClick={() => onDayTap(d)}
              title={
                bdayList
                  ? `🎂 ${bdayList.map((b) => b.display_name).join(", ")}`
                  : undefined
              }
              className={[
                "aspect-square rounded-lg flex flex-col items-center justify-start py-1 px-1 text-xs transition-transform active:scale-95 relative",
                inMonth ? "text-tg-text" : "text-tg-hint/60",
                today ? "ring-2 ring-tg-link" : "",
                bg,
              ].join(" ")}
            >
              <span className={today ? "font-bold" : "font-medium"}>{d.getDate()}</span>
              {bdayList && bdayList.length > 0 && (
                <span
                  role="button"
                  aria-label={`День рождения ${bdayList.map((b) => b.display_name).join(", ")}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    haptic("selection");
                    const first = bdayList[0];
                    setBirthdayPopover({
                      userId: first.user_id,
                      date: first.date,
                      displayName: first.display_name,
                    });
                  }}
                  className="absolute top-0.5 right-0.5 text-[10px] leading-none cursor-pointer"
                >
                  🎂
                  {bdayList.length > 1 && (
                    <span className="ml-0.5 text-[8px]">×{bdayList.length}</span>
                  )}
                </span>
              )}
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
