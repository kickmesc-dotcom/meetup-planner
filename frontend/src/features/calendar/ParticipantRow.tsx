import { addDays, format, startOfDay } from "date-fns";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import { AnimatePresence, LayoutGroup } from "framer-motion";
import type { AvailabilityRange, User } from "@/types";
import type { BirthdayCalendarEntry, CalendarMark } from "@/api/birthdays";
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
  /** ДР этого участника в окне (после фильтра по user_id в StripView). */
  birthdays?: BirthdayCalendarEntry[];
  /** Отметки лох/чухан этого участника в окне. */
  marks?: CalendarMark[];
  /** GHG6 E8.4: этот участник — активный «червь-пидор». Рисуем 🪱 у аватара. */
  isWorm?: boolean;
  /**
   * GHG6 CL1: фикс-ширина одной ячейки в пикселях. Если задано — строка не
   * растягивается на flex-1, а имеет ширину windowSpan × cellWidth. Используется
   * TimelineView для синхронизации сетки строк с горизонтальным скроллом и шапкой.
   * Если не задано — legacy-режим: 1fr (растягивается на доступную ширину).
   */
  cellWidth?: number;
}

export default function ParticipantRow({
  user,
  isMe,
  ranges,
  windowStart,
  windowSpan,
  birthdays = [],
  marks = [],
  isWorm = false,
  cellWidth,
}: Props) {
  const setEditing = useUI((s) => s.setEditingRangeId);
  const setBirthdayPopover = useUI((s) => s.setBirthdayPopover);
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

  // GHG6 BD1/BD5: индексы по YYYY-MM-DD, чтобы не сканить массивы в каждой ячейке.
  const bdayByDate = new Map(birthdays.map((b) => [b.date, b]));
  const marksByDate = new Map<string, Set<CalendarMark["type"]>>();
  for (const m of marks) {
    const set = marksByDate.get(m.date) ?? new Set();
    set.add(m.type);
    marksByDate.set(m.date, set);
  }
  const todayKey = format(startOfDay(new Date()), "yyyy-MM-dd");

  return (
    <div className="relative flex items-center border-b border-tg-secondary-bg/60">
      {/* GHG6 CL1: sticky-left делает колонку аватара "вмороженной" при
          горизонтальном скролле TimelineView. В StripView (легаси) родитель
          горизонтально не скроллится, поэтому sticky здесь — no-op. */}
      <div className="w-[60px] flex flex-col items-center py-1.5 shrink-0 sticky left-0 z-10 bg-tg-bg">
        <div className="relative">
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-medium overflow-hidden"
            style={{ background: user.color_hex }}
            title={isWorm ? `🪱 ${user.display_name} — червь-пидор` : user.display_name}
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
          {/* GHG6 E8.4: переходящее звание «червь-пидор». Бейдж висит у аватара
              того, кто сейчас активный носитель. */}
          {isWorm && (
            <span
              aria-label="Червь-пидор"
              className="absolute -bottom-1 -right-1 text-[14px] leading-none bg-tg-bg rounded-full px-0.5 shadow-sm"
            >
              🪱
            </span>
          )}
        </div>
        <div className="text-[10px] text-tg-hint truncate max-w-[60px] mt-0.5">
          {firstName(user.display_name)}
        </div>
      </div>

      {/* CAL1: overflow-hidden + contain жёстко удерживают пилюли в пределах
          разметки. Любая анимация framer-motion, выходящая за грань,
          клиппится контейнером.
          CL1: при заданном cellWidth — фикс-ширина (TimelineView), иначе
          1fr (legacy StripView). */}
      <div
        className={[
          "relative grid h-14 overflow-hidden [contain:layout_paint]",
          cellWidth ? "" : "flex-1",
        ].join(" ")}
        style={{
          gridTemplateColumns: cellWidth
            ? `repeat(${windowSpan}, ${cellWidth}px)`
            : `repeat(${windowSpan}, minmax(36px, 1fr))`,
          width: cellWidth ? windowSpan * cellWidth : undefined,
        }}
      >
        {Array.from({ length: windowSpan }).map((_, i) => {
          const dayStart = startOfDay(addDays(windowStart, i));
          const dayKey = format(dayStart, "yyyy-MM-dd");
          const dayEnd = addDays(dayStart, 1).getTime();
          const dayStartMs = dayStart.getTime();
          const covered = ranges.some((r) => {
            const s = new Date(r.starts_at).getTime();
            const e = new Date(r.ends_at).getTime();
            return s < dayEnd && e > dayStartMs;
          });
          const isLast = i === windowSpan - 1;
          const bday = bdayByDate.get(dayKey);
          const dayMarks = marksByDate.get(dayKey);
          // BD5: бейджи лох/чухан показываем только на прошедших днях, чтобы
          // в будущем не светить будущие записи (их там и не должно быть, но
          // на всякий случай защищаемся от часовых поясов и подмены даты).
          const isPast = dayKey < todayKey;
          const showLoser = isPast && dayMarks?.has("loser");
          const showChukhan = isPast && dayMarks?.has("chukhan");
          return (
            <div
              key={i}
              className={[
                "h-full relative",
                isLast ? "" : "border-r border-tg-secondary-bg/70",
              ].join(" ")}
            >
              <button
                type="button"
                onClick={() => onCellTap(i)}
                disabled={!isMe || createMut.isPending}
                className={[
                  "absolute inset-0",
                  isMe ? "active:bg-tg-secondary-bg/50" : "",
                  !covered
                    ? "bg-[repeating-linear-gradient(45deg,transparent_0_4px,rgba(239,68,68,0.08)_4px_8px)]"
                    : "",
                ].join(" ")}
                aria-label={`day ${i}`}
                title={!covered ? "Не отмечено — считается занятым" : undefined}
              />
              {/* GHG6 BD5: «прошедшие» бейджи лох/чухан в углу ячейки.
                  pointer-events-none — клик уходит на основную кнопку. */}
              {(showLoser || showChukhan) && (
                <div className="pointer-events-none absolute bottom-0.5 left-0.5 flex gap-0.5 text-[10px] leading-none">
                  {showLoser && <span aria-label="Был лохом">👑</span>}
                  {showChukhan && <span aria-label="Был чуханом">💩</span>}
                </div>
              )}
              {/* GHG6 BD1+BD3: 🎂 живёт в ячейке участника-именинника. Иконка —
                  отдельная кнопка с pointer-events:auto и stopPropagation,
                  чтобы тап по ячейке вне иконки работал как обычно. */}
              {bday && (
                <button
                  type="button"
                  aria-label={`День рождения ${user.display_name}`}
                  title={`🎂 ${user.display_name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    haptic("selection");
                    setBirthdayPopover({
                      userId: user.id,
                      date: bday.date,
                      displayName: user.display_name,
                    });
                  }}
                  className="absolute top-0.5 right-0.5 z-10 text-[12px] leading-none rounded-sm bg-tg-bg/70 px-0.5 active:scale-95"
                >
                  🎂
                </button>
              )}
            </div>
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
