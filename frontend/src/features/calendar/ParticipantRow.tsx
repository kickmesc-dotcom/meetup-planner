import { addDays, startOfDay } from "date-fns";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import { AnimatePresence, LayoutGroup } from "framer-motion";
import type { AvailabilityRange, User } from "@/types";
import { rangeToPillRect } from "./dateUtils";
import { useUI } from "@/store/ui";
import { createRange } from "@/api/availability";
import { haptic } from "@/tg/webapp";
import RangePill from "./RangePill";

interface Props {
  user: User;
  isMe: boolean;
  ranges: AvailabilityRange[];
  windowStart: Date;
  windowSpan: number;
}

export default function ParticipantRow({
  user,
  isMe,
  ranges,
  windowStart,
  windowSpan,
}: Props) {
  const setEditing = useUI((s) => s.setEditingRangeId);
  const qc = useQueryClient();

  const createMut = useMutation({
    mutationFn: createRange,
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["ranges"] });
      setEditing(created.id);
    },
    onError: () => haptic("error"),
  });

  const onCellTap = (dayIndex: number) => {
    if (!isMe) return;
    haptic("light");
    const dayStart = startOfDay(addDays(windowStart, dayIndex));
    const dayEnd = addDays(dayStart, 1);
    createMut.mutate({
      starts_at: dayStart.toISOString(),
      ends_at: dayEnd.toISOString(),
      all_day: true,
      status: 1,
      confidence: 3,
    });
  };

  return (
    <div className="relative flex items-center border-b border-tg-secondary-bg/60">
      <div className="w-[60px] flex flex-col items-center py-1.5 shrink-0">
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-medium overflow-hidden"
          style={{ background: user.color_hex }}
          title={user.display_name}
        >
          {user.avatar_url ? (
            <img
              src={user.avatar_url}
              alt={user.display_name}
              className="w-full h-full object-cover"
            />
          ) : (
            initials(user.display_name)
          )}
        </div>
        <div className="text-[10px] text-tg-hint truncate max-w-[60px] mt-0.5">
          {firstName(user.display_name)}
        </div>
      </div>

      {/* CAL1: overflow-hidden + contain жёстко удерживают пилюли в пределах
          разметки. Любая анимация framer-motion, выходящая за грань,
          клиппится контейнером. */}
      <div
        className="relative flex-1 grid h-14 overflow-hidden [contain:layout_paint]"
        style={{ gridTemplateColumns: `repeat(${windowSpan}, minmax(36px, 1fr))` }}
      >
        {Array.from({ length: windowSpan }).map((_, i) => {
          const dayStart = startOfDay(addDays(windowStart, i));
          const dayEnd = addDays(dayStart, 1).getTime();
          const dayStartMs = dayStart.getTime();
          const covered = ranges.some((r) => {
            const s = new Date(r.starts_at).getTime();
            const e = new Date(r.ends_at).getTime();
            return s < dayEnd && e > dayStartMs;
          });
          const isLast = i === windowSpan - 1;
          return (
            <button
              key={i}
              type="button"
              onClick={() => onCellTap(i)}
              disabled={!isMe || createMut.isPending}
              className={[
                "h-full relative",
                // CAL1: явная вертикальная сетка между клетками. Последняя ячейка без правой границы — её даст контейнер.
                isLast ? "" : "border-r border-tg-secondary-bg/70",
                isMe ? "active:bg-tg-secondary-bg/50" : "",
                !covered ? "bg-[repeating-linear-gradient(45deg,transparent_0_4px,rgba(239,68,68,0.08)_4px_8px)]" : "",
              ].join(" ")}
              aria-label={`day ${i}`}
              title={!covered ? "Не отмечено — считается занятым" : undefined}
            />
          );
        })}

        <LayoutGroup id={`row-${user.id}`}>
        <AnimatePresence>
          {ranges.map((r) => {
            const rect = rangeToPillRect(
              new Date(r.starts_at),
              new Date(r.ends_at),
              windowStart,
              windowSpan,
            );
            if (!rect) return null;
            return (
              <RangePill
                key={r.id}
                range={r}
                rect={rect}
                windowSpan={windowSpan}
                isOwn={isMe}
                onTap={() => {
                  if (isMe) {
                    haptic("light");
                    setEditing(r.id);
                  }
                }}
              />
            );
          })}
        </AnimatePresence>
        </LayoutGroup>
      </div>
    </div>
  );
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function firstName(name: string): string {
  return name.split(/\s+/)[0];
}
