import { useRef, useState } from "react";
import { addHours, addMinutes, startOfDay } from "date-fns";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import type { AvailabilityRange, User } from "@/types";
import { rangeToHourRect, statusColor, statusLabel } from "../dateUtils";
import { useUI } from "@/store/ui";
import { createRange } from "@/api/availability";
import { haptic } from "@/tg/webapp";

interface Props {
  day: Date;
  users: User[];
  meId: number;
  ranges: AvailabilityRange[];
}

const HOURS = Array.from({ length: 24 }, (_, i) => i);
const SLOT_HEIGHT_PX = 36;
const PARTICIPANT_COL_PX = 60;

/** Часовая шкала по аналогии с iOS Calendar — 24 строки сверху вниз,
 * участники как столбцы; drag по своему столбцу создаёт диапазон. */
export default function HoursView({ day, users, meId, ranges }: Props) {
  const setEditing = useUI((s) => s.setEditingRangeId);
  const qc = useQueryClient();

  const createMut = useMutation({
    mutationFn: createRange,
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["ranges"] });
      setEditing(created.id);
    },
  });

  const dayStart = startOfDay(day);

  return (
    <div className="flex-1 overflow-auto">
      <div
        className="grid relative"
        style={{
          gridTemplateColumns: `${PARTICIPANT_COL_PX}px repeat(${users.length}, minmax(70px, 1fr))`,
        }}
      >
        {/* Header строка с участниками (sticky) */}
        <div className="sticky top-0 z-20 bg-tg-bg border-b border-tg-secondary-bg" />
        {users.map((u) => (
          <div
            key={`hdr-${u.id}`}
            className="sticky top-0 z-20 bg-tg-bg border-b border-tg-secondary-bg flex flex-col items-center py-1"
          >
            <div
              className="w-8 h-8 rounded-full flex items-center justify-center text-white text-[11px] font-medium overflow-hidden shrink-0"
              style={{ background: u.color_hex }}
            >
              {u.avatar_url ? (
                <img src={u.avatar_url} alt="" className="w-full h-full object-cover" />
              ) : (
                u.display_name[0]?.toUpperCase()
              )}
            </div>
            <div className="text-[9px] text-tg-hint truncate max-w-[64px] mt-0.5">
              {u.display_name.split(/\s+/)[0]}
            </div>
          </div>
        ))}

        {/* Сетка по часам: 24 строки, в каждой строке N+1 ячеек */}
        {HOURS.map((h) => (
          <Row
            key={h}
            hour={h}
            users={users}
            meId={meId}
            day={day}
            ranges={ranges}
            onCreate={(s, e) => {
              haptic("light");
              createMut.mutate({
                starts_at: s.toISOString(),
                ends_at: e.toISOString(),
                all_day: false,
                status: 1,
                confidence: 3,
              });
            }}
            onTapRange={(r) => {
              if (r.user_id !== meId) return;
              haptic("light");
              setEditing(r.id);
            }}
            dayStart={dayStart}
          />
        ))}
      </div>
    </div>
  );
}

function Row({
  hour,
  users,
  meId,
  day,
  ranges,
  onCreate,
  onTapRange,
  dayStart,
}: {
  hour: number;
  users: User[];
  meId: number;
  day: Date;
  ranges: AvailabilityRange[];
  onCreate: (start: Date, end: Date) => void;
  onTapRange: (r: AvailabilityRange) => void;
  dayStart: Date;
}) {
  return (
    <>
      <div
        className="text-[10px] text-tg-hint pr-2 text-right border-r border-tg-secondary-bg/40 flex items-start pt-0.5"
        style={{ height: SLOT_HEIGHT_PX }}
      >
        {String(hour).padStart(2, "0")}:00
      </div>
      {users.map((u) => (
        <UserSlot
          key={`${hour}-${u.id}`}
          isMe={u.id === meId}
          hour={hour}
          dayStart={dayStart}
          ranges={ranges.filter((r) => r.user_id === u.id)}
          day={day}
          onCreate={onCreate}
          onTapRange={onTapRange}
        />
      ))}
    </>
  );
}

function UserSlot({
  isMe,
  hour,
  dayStart,
  ranges,
  day,
  onCreate,
  onTapRange,
}: {
  isMe: boolean;
  hour: number;
  dayStart: Date;
  ranges: AvailabilityRange[];
  day: Date;
  onCreate: (start: Date, end: Date) => void;
  onTapRange: (r: AvailabilityRange) => void;
}) {
  const cellRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ startY: number; endY: number } | null>(null);

  const onPointerDown = (e: React.PointerEvent) => {
    if (!isMe) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const rect = cellRef.current!.getBoundingClientRect();
    setDrag({ startY: e.clientY - rect.top, endY: e.clientY - rect.top });
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag) return;
    const rect = cellRef.current!.getBoundingClientRect();
    setDrag({ ...drag, endY: e.clientY - rect.top });
  };

  const onPointerUp = () => {
    if (!drag) return;
    const minutesPerPx = 60 / SLOT_HEIGHT_PX;
    const startMin = Math.round((Math.min(drag.startY, drag.endY) * minutesPerPx) / 15) * 15;
    const endMinRaw = Math.max(drag.startY, drag.endY) * minutesPerPx;
    const endMin = Math.max(startMin + 15, Math.round(endMinRaw / 15) * 15);
    setDrag(null);
    const startsAt = addMinutes(addHours(dayStart, hour), startMin);
    const endsAt = addMinutes(addHours(dayStart, hour), endMin);
    onCreate(startsAt, endsAt);
  };

  return (
    <div
      ref={cellRef}
      onPointerDown={isMe ? onPointerDown : undefined}
      onPointerMove={isMe ? onPointerMove : undefined}
      onPointerUp={isMe ? onPointerUp : undefined}
      onPointerCancel={() => setDrag(null)}
      className={[
        "relative border-r border-b border-tg-secondary-bg/30",
        isMe ? "active:bg-tg-secondary-bg/40 cursor-pointer touch-none" : "",
      ].join(" ")}
      style={{ height: SLOT_HEIGHT_PX }}
    >
      {drag && (
        <div
          className="absolute inset-x-0 bg-status-free/30 border-y border-status-free pointer-events-none"
          style={{
            top: Math.min(drag.startY, drag.endY),
            height: Math.abs(drag.endY - drag.startY),
          }}
        />
      )}
      <AnimatePresence>
        {ranges.map((r) => {
          const rect = rangeToHourRect(new Date(r.starts_at), new Date(r.ends_at), day);
          if (!rect) return null;
          // Только если этот hour — стартовый, рисуем пилюлю с абсолютным позиционированием
          if (Math.floor(rect.startIndex) !== hour) return null;
          const totalHeight = rect.span * SLOT_HEIGHT_PX;
          const offsetY = (rect.startIndex - hour) * SLOT_HEIGHT_PX;
          return (
            <motion.button
              key={r.id}
              layout
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.85, opacity: 0 }}
              onClick={(e) => {
                e.stopPropagation();
                onTapRange(r);
              }}
              className="absolute inset-x-1 rounded-md text-white text-[10px] font-medium flex items-start justify-start px-1.5 py-1 shadow-sm overflow-hidden"
              style={{
                top: offsetY,
                height: totalHeight - 2,
                background: statusColor(r.status),
                opacity: r.confidence >= 4 ? 0.7 : 0.95,
                pointerEvents: isMe ? "auto" : "none",
                zIndex: 5,
              }}
            >
              <span className="truncate">{r.note ?? statusLabel(r.status)}</span>
            </motion.button>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
