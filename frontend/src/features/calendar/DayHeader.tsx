import { format, isToday, isWeekend } from "date-fns";
import { ru } from "date-fns/locale";

interface Props {
  days: Date[];
}

export default function DayHeader({ days }: Props) {
  return (
    <div
      className="grid border-b border-tg-secondary-bg bg-tg-bg sticky top-0 z-10 pl-[72px]"
      style={{ gridTemplateColumns: `repeat(${days.length}, minmax(36px, 1fr))` }}
    >
      {days.map((d) => {
        const today = isToday(d);
        const we = isWeekend(d);
        return (
          <div
            key={d.toISOString()}
            className={[
              "py-1.5 text-center select-none",
              today ? "text-tg-link font-semibold" : we ? "text-status-busy/70" : "text-tg-text",
            ].join(" ")}
          >
            <div className="text-[10px] uppercase tracking-wide text-tg-hint">
              {format(d, "EEEEEE", { locale: ru })}
            </div>
            <div className="text-sm leading-none">{format(d, "d")}</div>
          </div>
        );
      })}
    </div>
  );
}
