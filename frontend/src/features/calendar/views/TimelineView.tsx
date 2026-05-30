import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { addDays, format, isToday, isWeekend, startOfDay } from "date-fns";
import type { AvailabilityRange, User } from "@/types";
import type { BirthdayCalendarEntry, CalendarMark, CurrentTitles } from "@/api/birthdays";
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
 * CL3 — нативный horizontal scroll + scroll-snap proximity на ячейках шапки
 * (см. .calendar-timeline-scroll в styles.css). Магнит к ближайшему дню
 * получается бесплатно от браузера, нативный momentum-scroll на iOS/Android
 * сохранён (без JS pointermove-перехватов). goToday() и shiftAnchor через
 * scrollTo({behavior:'smooth'}); первый mount — instant, чтобы не было
 * «вылета» из позиции 0.
 * Этап 3+ добавит CL2 (виртуализация), CL4 (motion blur), CL7 (confidence-
 * заливка), CL8/CL9 (RangeEditor + partial fill).
 */

const WINDOW_HALF = 21;
const AVATAR_COL_WIDTH = 60;
const CELL_WIDTH_MIN = 24;
const CELL_WIDTH_MAX = 120;
// CL12: дефолт «Неделя» — 7 дней должны помещаться в ширину контейнера.
// 7.4 даёт небольшой "хвост" следующего дня, чтобы пользователь видел, что
// справа есть продолжение (хороший аффорданс).
const CELLS_PER_VIEWPORT_DEFAULT = 7.4;
// CL2: overscan — сколько дней по краям видимого окна рендерим «впрок», чтобы
// при быстром скролле пользователь не видел дырки от ещё-не-смонтированных
// ячеек. 14 — компромисс: при cellWidth=24 (минимум) это 336px по краям,
// что больше типичного flick-расстояния.
const OVERSCAN_DAYS = 14;

interface Props {
  users: User[];
  meId: number;
  anchor: Date;
  ranges: AvailabilityRange[];
  birthdays?: BirthdayCalendarEntry[];
  marks?: CalendarMark[];
  /** GHG7 P2.1.a: актуальные звания для иконок-«шапок» поверх аватарки. */
  titles?: CurrentTitles | null;
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
  titles = null,
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

  // CL2: виртуализация. Считаем индексы видимых дней по scrollLeft +
  // clientWidth, расширяем на OVERSCAN_DAYS в обе стороны и передаём в
  // ParticipantRow/TimelineHeader. Невидимые ячейки рендерятся как пустые
  // div'ы, что экономит на covered-проверке + confidenceFillForDay (heaviest
  // part) + bday/marks lookup в каждой ячейке. При 6 строках это 6 × 43 = 258
  // ячеек; с виртуализацией остаётся ~6 × (7 + 28) ≈ 210 → экономия скромная
  // на десктопе, но заметная на старых iPhone, особенно при scroll-анимации
  // и движении слайдера зума (re-render всей сетки каждый кадр).
  const [scrollLeft, setScrollLeft] = useState(0);
  const [clientWidth, setClientWidth] = useState(0);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => setScrollLeft(el.scrollLeft);
    const onResize = () => setClientWidth(el.clientWidth);
    onResize();
    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    const ro = new ResizeObserver(onResize);
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", onScroll);
      ro.disconnect();
    };
  }, []);

  // Видимая область внутри days-сетки (исключая sticky-аватар-колонку).
  const viewLeft = Math.max(0, scrollLeft - AVATAR_COL_WIDTH);
  const viewRight = scrollLeft + clientWidth - AVATAR_COL_WIDTH;
  const rawFirstVisible = Math.floor(viewLeft / Math.max(1, cellWidth));
  const rawLastVisible = Math.ceil(viewRight / Math.max(1, cellWidth));
  const visibleStart = Math.max(0, rawFirstVisible - OVERSCAN_DAYS);
  const visibleEnd = Math.min(span - 1, rawLastVisible + OVERSCAN_DAYS);

  // CL6.b + CL3: при изменении anchor (вкл. goToday / shiftAnchor) скроллим
  // к anchor так, чтобы он оказался по центру viewport. Smooth-scroll везде,
  // кроме первого mount — иначе пользователь видит «вылет» ленты из позиции 0.
  // Изменение cellWidth (зум) — тоже smooth: визуально лучше, чем мгновенный
  // прыжок при движении слайдера.
  const didInitialScrollRef = useRef(false);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const anchorIndex = WINDOW_HALF; // anchor по построению в центре окна
    const target = AVATAR_COL_WIDTH + anchorIndex * cellWidth - el.clientWidth / 2 + cellWidth / 2;
    const left = Math.max(0, target);
    if (!didInitialScrollRef.current) {
      // На первом рендере scrollTo с behavior:'smooth' игнорируется, если
      // элемент только что появился; используем явный instant.
      el.scrollLeft = left;
      didInitialScrollRef.current = true;
    } else {
      el.scrollTo({ left, behavior: "smooth" });
    }
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
        <TimelineHeader
          days={days}
          cellWidth={cellWidth}
          gameDates={gameDates}
          visibleStart={visibleStart}
          visibleEnd={visibleEnd}
        />
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
            cellWidth={cellWidth}
            visibleStart={visibleStart}
            visibleEnd={visibleEnd}
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
  visibleStart,
  visibleEnd,
}: {
  days: Date[];
  cellWidth: number;
  gameDates?: Set<string>;
  /**
   * GHG6 CL2: индексы видимого диапазона дней (включительно, с учётом
   * OVERSCAN). Дни за пределами схлопываются в два grid-спейсера —
   * `grid-column: span N` — чтобы не плодить DOM-узлы и не считать
   * для них isToday/isWeekend/gameDates lookup на каждом ре-рендере.
   * Если границы не заданы — рендерим всё, как раньше.
   */
  visibleStart?: number;
  visibleEnd?: number;
}) {
  const start = visibleStart ?? 0;
  const end = visibleEnd ?? days.length - 1;
  const leftSpan = Math.max(0, start);
  const rightSpan = Math.max(0, days.length - 1 - end);
  return (
    <div
      className="grid sticky top-0 z-20 bg-tg-bg border-b border-tg-secondary-bg/80"
      style={{
        gridTemplateColumns: `repeat(${days.length}, ${cellWidth}px)`,
        paddingLeft: AVATAR_COL_WIDTH,
        width: AVATAR_COL_WIDTH + days.length * cellWidth,
      }}
    >
      {leftSpan > 0 && (
        <div aria-hidden style={{ gridColumn: `span ${leftSpan}` }} />
      )}
      {days.slice(start, end + 1).map((d, sliceIdx) => {
        const idx = start + sliceIdx;
        const today = isToday(d);
        const we = isWeekend(d);
        const showMonth = d.getDate() === 1 || idx === 0;
        const isLast = idx === days.length - 1;
        return (
          <div
            key={d.toISOString()}
            className={[
              "timeline-day py-1.5 text-center select-none relative",
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
      {rightSpan > 0 && (
        <div aria-hidden style={{ gridColumn: `span ${rightSpan}` }} />
      )}
    </div>
  );
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}
