import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { addDays, format, isToday, isWeekend, startOfDay } from "date-fns";
import type { AvailabilityRange, User } from "@/types";
import type { BirthdayCalendarEntry, CalendarMark } from "@/api/birthdays";
import { ruWeekdayShort } from "../dateUtils";
import ParticipantRow from "../ParticipantRow";
import { useUI } from "@/store/ui";

/**
 * GHG6 P3 — горизонтальный таймлайн-вид календаря.
 *
 * Этап 1 (CL1): каркас. Header sticky-top, ParticipantRow sticky-left, общий
 * горизонтальный скролл для шапки и строк (один overflow-x-auto контейнер).
 * Этап 2: CL6.a — динамический cellWidth по ширине контейнера (default
 * ≈containerW/7.4, неделя помещается). CL12 — дефолт «Неделя».
 * Этап 3+ добавит CL3 (жесты), CL5 (слайдер зума), CL2 (виртуализация),
 * CL4 (motion blur), CL7 (confidence-заливка), CL13 (нижняя плашка),
 * CL6.b («К сегодня»).
 */

const WINDOW_HALF = 21;
const AVATAR_COL_WIDTH = 60;
const CELL_WIDTH_MIN = 24;
const CELL_WIDTH_MAX = 120;
// CL12: дефолт «Неделя» — 7 дней должны помещаться в ширину контейнера.
// 7.4 даёт небольшой "хвост" следующего дня, чтобы пользователь видел, что
// справа есть продолжение (хороший аффорданс).
const CELLS_PER_VIEWPORT_DEFAULT = 7.4;

interface Props {
  users: User[];
  meId: number;
  anchor: Date;
  ranges: AvailabilityRange[];
  birthdays?: BirthdayCalendarEntry[];
  marks?: CalendarMark[];
  /** GHG6 E8.4: user.id активного «червя-пидора», если есть. */
  wormUserId?: number | null;
  /** GHG6 E6: даты (YYYY-MM-DD) с запланированной игрой — 🎮 в шапке дня. */
  gameDates?: Set<string>;
  isPending: boolean;
}

export default function TimelineView({
  users,
  meId,
  anchor,
  ranges,
  birthdays = [],
  marks = [],
  wormUserId = null,
  gameDates,
  isPending,
}: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // CL6.a: автоматический cellWidth — стартовое предположение 56, потом
  // ResizeObserver подгоняет под фактическую ширину контейнера.
  const [autoCellWidth, setAutoCellWidth] = useState<number>(56);

  // CL5: пользовательский override (слайдер зума / пресет). Если задан,
  // перебивает авто. null = «авто».
  const userCellWidth = useUI((s) => s.timelineCellWidth);
  const cellWidth = userCellWidth ?? autoCellWidth;

  // ResizeObserver: пересчёт автоширины при ресайзе viewport (поворот экрана,
  // открытие/закрытие keyboard на iOS).
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const recompute = () => {
      const avail = el.clientWidth - AVATAR_COL_WIDTH;
      if (avail <= 0) return;
      const next = clamp(
        Math.floor(avail / CELLS_PER_VIEWPORT_DEFAULT),
        CELL_WIDTH_MIN,
        CELL_WIDTH_MAX,
      );
      setAutoCellWidth(next);
    };
    recompute();
    const ro = new ResizeObserver(recompute);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const windowStart = startOfDay(addDays(anchor, -WINDOW_HALF));
  const span = WINDOW_HALF * 2 + 1;
  const totalWidth = span * cellWidth;
  const days = Array.from({ length: span }, (_, i) => addDays(windowStart, i));

  // CL6.b (частично): при изменении anchor — скроллим к anchor так, чтобы он
  // оказался по центру viewport. Полноценная кнопка «📍 К сегодня»
  // и smooth-scroll придут в CL13.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const anchorIndex = WINDOW_HALF; // anchor по построению в центре окна
    const target = AVATAR_COL_WIDTH + anchorIndex * cellWidth - el.clientWidth / 2 + cellWidth / 2;
    el.scrollLeft = Math.max(0, target);
  }, [anchor, cellWidth]);

  void meId;

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-x-auto overflow-y-auto calendar-timeline-scroll"
    >
      {/* Внутренний слой имеет фиксированную ширину = avatar(60) + days × cellWidth.
          Шапка и строки делят этот слой и один и тот же горизонтальный скролл —
          синхронизация бесплатно. */}
      <div style={{ width: totalWidth + AVATAR_COL_WIDTH, minWidth: "100%" }}>
        <TimelineHeader days={days} cellWidth={cellWidth} gameDates={gameDates} />
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
            isWorm={wormUserId === u.id}
            cellWidth={cellWidth}
          />
        ))}
        {isPending && (
          <div className="p-3 text-center text-xs text-tg-hint">Загрузка…</div>
        )}
      </div>
    </div>
  );
}

function TimelineHeader({
  days,
  cellWidth,
  gameDates,
}: {
  days: Date[];
  cellWidth: number;
  gameDates?: Set<string>;
}) {
  return (
    <div
      className="grid sticky top-0 z-20 bg-tg-bg border-b border-tg-secondary-bg/80"
      style={{
        gridTemplateColumns: `repeat(${days.length}, ${cellWidth}px)`,
        paddingLeft: AVATAR_COL_WIDTH,
        width: AVATAR_COL_WIDTH + days.length * cellWidth,
      }}
    >
      {days.map((d, idx) => {
        const today = isToday(d);
        const we = isWeekend(d);
        const showMonth = d.getDate() === 1 || idx === 0;
        const isLast = idx === days.length - 1;
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
  );
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}
