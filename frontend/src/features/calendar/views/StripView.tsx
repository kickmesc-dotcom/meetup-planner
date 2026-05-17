import { useMemo } from "react";
import { format, isToday, isWeekend, startOfDay } from "date-fns";
import type { AvailabilityRange, User } from "@/types";
import type { BirthdayCalendarEntry } from "@/api/birthdays";
import { buildDaysWindow, ruWeekdayShort } from "../dateUtils";
import ParticipantRow from "../ParticipantRow";

interface Props {
  windowStart: Date;
  span: number;
  users: User[];
  meId: number;
  ranges: AvailabilityRange[];
  birthdays?: BirthdayCalendarEntry[];
  isPending: boolean;
}

export default function StripView({
  windowStart,
  span,
  users,
  meId,
  ranges,
  birthdays = [],
  isPending,
}: Props) {
  const days = buildDaysWindow(startOfDay(windowStart), span);
  const bdayIndex = useMemo(() => {
    const idx = new Map<string, string[]>();
    for (const b of birthdays) {
      const arr = idx.get(b.date) ?? [];
      arr.push(b.display_name);
      idx.set(b.date, arr);
    }
    return idx;
  }, [birthdays]);

  return (
    <>
      <div
        className="grid border-b border-tg-secondary-bg/80 bg-tg-bg sticky top-0 z-10 pl-[60px]"
        style={{ gridTemplateColumns: `repeat(${span}, minmax(36px, 1fr))` }}
      >
        {days.map((d, idx) => {
          const today = isToday(d);
          const we = isWeekend(d);
          const showMonth = d.getDate() === 1 || d.getTime() === days[0].getTime();
          const dayKey = format(d, "yyyy-MM-dd");
          const bdayNames = bdayIndex.get(dayKey);
          const isLast = idx === days.length - 1;
          return (
            <div
              key={d.toISOString()}
              title={bdayNames ? `🎂 ${bdayNames.join(", ")}` : undefined}
              className={[
                "py-1.5 text-center select-none relative",
                isLast ? "" : "border-r border-tg-secondary-bg/70",
                today
                  ? "text-tg-link font-semibold"
                  : we
                    ? "text-status-busy/70"
                    : "text-tg-text",
              ].join(" ")}
            >
              <div className="text-[10px] uppercase tracking-wide text-tg-hint">
                {ruWeekdayShort(d.getDay())}
              </div>
              <div className="text-sm leading-none">
                {showMonth ? format(d, "d.MM") : d.getDate()}
              </div>
              {bdayNames && (
                <span
                  aria-label="День рождения"
                  className="absolute top-0 right-0 text-[10px] leading-none"
                >
                  🎂
                </span>
              )}
              {today && (
                <div className="absolute left-1/2 -translate-x-1/2 -bottom-px h-0.5 w-6 rounded-full bg-tg-link" />
              )}
            </div>
          );
        })}
      </div>
      <div className="flex-1 overflow-y-auto">
        {users.map((u) => (
          <ParticipantRow
            key={u.id}
            user={u}
            isMe={u.id === meId}
            ranges={ranges.filter((r) => r.user_id === u.id)}
            windowStart={windowStart}
            windowSpan={span}
          />
        ))}
        {isPending && (
          <div className="p-3 text-center text-xs text-tg-hint">Загрузка…</div>
        )}
      </div>
    </>
  );
}
