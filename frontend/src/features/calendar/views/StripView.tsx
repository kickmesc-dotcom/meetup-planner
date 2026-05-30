import { format, isToday, isWeekend, startOfDay } from "date-fns";
import type { AvailabilityRange, User } from "@/types";
import type { BirthdayCalendarEntry, CalendarMark, CurrentTitles } from "@/api/birthdays";
import { buildDaysWindow, ruWeekdayShort } from "../dateUtils";
import ParticipantRow from "../ParticipantRow";

interface Props {
  windowStart: Date;
  span: number;
  users: User[];
  meId: number;
  ranges: AvailabilityRange[];
  birthdays?: BirthdayCalendarEntry[];
  marks?: CalendarMark[];
  /** GHG7 P2.1.a: актуальные звания для иконок-«шапок» поверх аватарки. */
  titles?: CurrentTitles | null;
  /** GHG6 E6: даты (YYYY-MM-DD) с запланированной игрой — рисуем 🎮 в шапке дня. */
  gameDates?: Set<string>;
  isPending: boolean;
}

export default function StripView({
  windowStart,
  span,
  users,
  meId,
  ranges,
  birthdays = [],
  marks = [],
  titles = null,
  gameDates,
  isPending,
}: Props) {
  const days = buildDaysWindow(startOfDay(windowStart), span);

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
          const isLast = idx === days.length - 1;
          // GHG6 BD1: 🎂 в шапке дня больше не рисуем — теперь иконка живёт
          // в ячейке участника-именинника. Так понятно, чей именно ДР.
          return (
            <div
              key={d.toISOString()}
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
              {gameDates?.has(format(d, "yyyy-MM-dd")) && (
                <div
                  className="absolute top-0 right-0.5 text-[10px] leading-none"
                  title="Запланированная игра"
                >
                  🎮
                </div>
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
            birthdays={birthdays.filter((b) => b.user_id === u.id)}
            marks={marks.filter((m) => m.user_id === u.id)}
            titles={titles}
          />
        ))}
        {isPending && (
          <div className="p-3 text-center text-xs text-tg-hint">Загрузка…</div>
        )}
      </div>
    </>
  );
}
