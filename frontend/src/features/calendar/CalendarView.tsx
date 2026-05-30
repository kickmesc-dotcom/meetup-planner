import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDrag, usePinch } from "@use-gesture/react";
import { fetchRanges } from "@/api/availability";
import {
  fetchBirthdaysInWindow,
  fetchCalendarMarks,
  fetchCurrentTitles,
  fetchScheduledGames,
} from "@/api/birthdays";
import { fetchCalendarTimelineFlag } from "@/api/admin";
import type { User } from "@/types";
import { useUI, isStripZoom, isMonthGridZoom } from "@/store/ui";
import { haptic } from "@/tg/webapp";
import { windowForZoom } from "./dateUtils";
import NavBar from "./NavBar";
import ZoomController from "./ZoomController";
import RangeEditorSheet from "../editor/RangeEditorSheet";
import ActionBar from "../actions/ActionBar";
import AutoPickSheet from "../actions/AutoPickSheet";
import LoserSheet from "../actions/LoserSheet";
import PollSheet from "../actions/PollSheet";
import StripView from "./views/StripView";
import TimelineView from "./views/TimelineView";
import TimelineNavBar from "./views/TimelineNavBar";
import BirthdayPopover from "./BirthdayPopover";
import LoserReasonPopover from "./LoserReasonPopover";
import HoursView from "./views/HoursView";
import MonthView from "./views/MonthView";
import YearView from "./views/YearView";
import AllYearsView from "./views/AllYearsView";

interface Props {
  users: User[];
  meId: number;
}

export default function CalendarView({ users, meId }: Props) {
  const zoom = useUI((s) => s.zoom);
  const anchor = useUI((s) => s.anchorDate);
  const editingRangeId = useUI((s) => s.editingRangeId);
  const showAutoPick = useUI((s) => s.showAutoPickSheet);
  const showLoser = useUI((s) => s.showLoserSheet);
  const showPoll = useUI((s) => s.showPollSheet);
  const zoomIn = useUI((s) => s.zoomIn);
  const zoomOut = useUI((s) => s.zoomOut);
  const shift = useUI((s) => s.shiftAnchor);

  // GHG6 CL0: master-toggle нового таймлайн-вида. Пока TimelineView ещё не
  // реализован (CL1+), оба значения флага рендерят legacy-вид. Запрос всё
  // равно делаем — чтобы как только CL1 приземлится, ветвление включилось
  // без дополнительной выкладки.
  const timelineFlag = useQuery({
    queryKey: ["admin", "calendar", "timeline"],
    queryFn: fetchCalendarTimelineFlag,
    staleTime: 60_000,
  });
  // GHG6 P3 CL1: пока новый таймлайн в стадии каркаса (нет жестов, зума,
  // боттом-плашки), дефолт = false. Включается админкой через
  // PUT /admin/calendar/timeline {enabled:true} — для ручного теста.
const timelineEnabled = timelineFlag.data?.enabled ?? false;

  // CL1: при включённом timeline окно фиксируется в ±21 день от anchor (43 дня).
  // Это позволяет существующим useQuery подтянуть нужный диапазон одним
  // запросом — TimelineView сам отсюда читает windowStart/span.
  const win = useMemo(() => {
    if (timelineEnabled) {
      const start = new Date(anchor);
      start.setDate(start.getDate() - 21);
      start.setHours(0, 0, 0, 0);
      const end = new Date(start);
      end.setDate(end.getDate() + 43);
      return { start, end };
    }
    return windowForZoom(zoom, anchor);
  }, [timelineEnabled, zoom, anchor]);

  const ranges = useQuery({
    queryKey: ["ranges", win.start.toISOString(), win.end.toISOString()],
    queryFn: () => fetchRanges(win.start, win.end),
    staleTime: 15_000,
  });

  // BD-CAL1: ДР-шки в текущем окне. staleTime короткий, чтобы после ввода
  // в админке («год известен — сохранил») значок 🎂 появился без перезагрузки.
  const birthdays = useQuery({
    queryKey: ["birthdays", win.start.toISOString(), win.end.toISOString()],
    queryFn: () => fetchBirthdaysInWindow(win.start, win.end),
    staleTime: 10_000,
  });

  // GHG6 BD4: отметки лох/чухан в окне. Используются для 👑/💩 на прошедших днях.
  const marks = useQuery({
    queryKey: ["calendar-marks", win.start.toISOString(), win.end.toISOString()],
    queryFn: () => fetchCalendarMarks(win.start, win.end),
    staleTime: 30_000,
  });

  // GHG7 P2.1.a: актуальные звания (червь, чухан недели, лох дня, главный лох,
  // ДР сегодня) одним запросом — для иконок-«шапок» поверх аватарки. Не от
  // окна, запрос «глобальный». 30s staleTime: звания меняются редко.
  // Заменяет прежний отдельный ["worm-current"] — worm теперь приходит здесь.
  const titles = useQuery({
    queryKey: ["titles-current"],
    queryFn: fetchCurrentTitles,
    staleTime: 30_000,
  });

  // GHG6 E6: запланированные игры в окне — рисуем иконку 🎮 в углу дня.
  // Окно совпадает с окном ranges, чтобы один и тот же refresh охватывал всё.
  const games = useQuery({
    queryKey: ["games-scheduled", win.start.toISOString(), win.end.toISOString()],
    queryFn: () => fetchScheduledGames(win.start, win.end),
    staleTime: 30_000,
  });

  const containerRef = useRef<HTMLDivElement>(null);

  // F6: визуальные подсказки по краям — показываем стрелку, когда жест в процессе.
  const [hintEdge, setHintEdge] = useState<"left" | "right" | "in" | "out" | null>(null);
  const hintTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const showHint = (edge: typeof hintEdge) => {
    setHintEdge(edge);
    if (hintTimerRef.current) clearTimeout(hintTimerRef.current);
    if (edge !== null) {
      hintTimerRef.current = setTimeout(() => setHintEdge(null), 450);
    }
  };
  useEffect(() => () => {
    if (hintTimerRef.current) clearTimeout(hintTimerRef.current);
  }, []);

  // Pinch zoom: scale up — больше деталей, scale down — общий вид.
  const lastPinchRef = useRef(0);
  usePinch(
    ({ offset: [scale] }) => {
      const now = Date.now();
      if (now - lastPinchRef.current < 220) return;
      if (scale > 1.35) {
        lastPinchRef.current = now;
        haptic("medium");
        showHint("in");
        zoomIn();
      } else if (scale < 0.75) {
        lastPinchRef.current = now;
        haptic("medium");
        showHint("out");
        zoomOut();
      } else if (scale > 1.05) {
        showHint("in");
      } else if (scale < 0.95) {
        showHint("out");
      }
    },
    { target: containerRef, scaleBounds: { min: 0.3, max: 3 } },
  );

  // F5+F6: горизонтальный свайп = shiftAnchor. Порог 60px, чтобы не путать
  // со скроллом списка участников вниз. axis: 'x' прибит явно.
  useDrag(
    ({ last, movement: [mx], cancel, canceled, swipe: [sx] }) => {
      if (canceled) return;
      // Live-подсказка по краю при достижении порога
      if (!last) {
        if (mx > 30) showHint("right");
        else if (mx < -30) showHint("left");
        else showHint(null);
        return;
      }
      const decisiveSwipe = sx !== 0;
      const dist = Math.abs(mx);
      if (decisiveSwipe || dist > 60) {
        const dir: 1 | -1 = mx > 0 ? -1 : 1;
        haptic("light");
        shift(dir);
      }
      showHint(null);
      cancel();
    },
    { target: containerRef, axis: "x", filterTaps: true, pointer: { touch: true } },
  );

  useEffect(() => {
    const onVis = () => {
      if (!document.hidden) ranges.refetch();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [ranges]);

  const data = ranges.data ?? [];
  const bdays = birthdays.data ?? [];
  const calMarks = marks.data ?? [];
  const titlesData = titles.data ?? null;
  const gameDates = new Set((games.data ?? []).map((g) => g.date));
  const isPending = ranges.isPending;

  // GHG6 P3 CL13: при включённом timeline мы переиспользуем legacy YearView /
  // AllYearsView для крупных zoom-уровней — TimelineView имеет смысл только
  // в диапазоне day/week/month. Так же кейс zoom='hour' остаётся на HoursView
  // (одна суточная шкала), а 'threeMonths/sixMonths' — на MonthView (сетка).
  const useTimelineForCurrentZoom =
    timelineEnabled && (zoom === "day" || zoom === "week" || zoom === "month");

  let body: React.ReactNode = null;
  if (useTimelineForCurrentZoom) {
    body = (
      <TimelineView
        users={users}
        meId={meId}
        anchor={anchor}
        ranges={data}
        birthdays={bdays}
        marks={calMarks}
        titles={titlesData}
        gameDates={gameDates}
        isPending={isPending}
      />
    );
  } else if (zoom === "hour") {
    body = <HoursView day={win.start} users={users} meId={meId} ranges={data} />;
  } else if (isStripZoom(zoom)) {
    const span = zoom === "day" ? 1 : 7;
    body = (
      <StripView
        windowStart={win.start}
        span={span}
        users={users}
        meId={meId}
        ranges={data}
        birthdays={bdays}
        marks={calMarks}
        titles={titlesData}
        gameDates={gameDates}
        isPending={isPending}
      />
    );
  } else if (isMonthGridZoom(zoom)) {
    const months = zoom === "month" ? 1 : zoom === "threeMonths" ? 3 : 6;
    body = (
      <MonthView
        months={months}
        anchor={anchor}
        ranges={data}
        users={users}
        birthdays={bdays}
        gameDates={gameDates}
      />
    );
  } else if (zoom === "year") {
    body = <YearView anchor={anchor} ranges={data} users={users} />;
  } else if (zoom === "allYears") {
    body = <AllYearsView anchor={anchor} />;
  }

  return (
    <div
      ref={containerRef}
      className="relative flex h-full flex-col calendar-pan-container"
    >
      {/* CL1: NavBar/ZoomController нужны только legacy-веткам.
          У TimelineView (CL13) собственная нижняя плашка TimelineNavBar. */}
      {!useTimelineForCurrentZoom && <NavBar />}
      {!useTimelineForCurrentZoom && <ZoomController />}
      {body}
      {timelineEnabled && (
        <TimelineNavBar
          isOnToday={
            anchor.toDateString() === new Date().toDateString()
          }
        />
      )}
      <ActionBar />

      {/* F6: edge hints. Стрелки/иконки появляются при жесте, гасятся через 450ms. */}
      <GestureHint edge={hintEdge} />

      {editingRangeId !== null && (
        <RangeEditorSheet
          rangeId={editingRangeId}
          windowStart={win.start}
          windowEnd={win.end}
          meId={meId}
        />
      )}
      {showAutoPick && <AutoPickSheet />}
      {showLoser && <LoserSheet />}
      {showPoll && <PollSheet users={users} />}

      {/* GHG6 BD2: глобальный поповер ДР; рендерится поверх всего календаря. */}
      <BirthdayPopover />
      {/* GHG7 P0.2.e: попап причины ролла по клику на 👑. */}
      <LoserReasonPopover />
    </div>
  );
}

function GestureHint({ edge }: { edge: "left" | "right" | "in" | "out" | null }) {
  if (edge === null) return null;
  const common =
    "pointer-events-none absolute z-30 flex items-center justify-center rounded-full bg-tg-button/85 text-tg-button-text shadow-lg transition-opacity";
  if (edge === "left" || edge === "right") {
    const side = edge === "left" ? "right-3" : "left-3";
    const arrow = edge === "left" ? "›" : "‹";
    const label = edge === "left" ? "вперёд" : "назад";
    return (
      <div
        className={`${common} ${side} top-1/2 -translate-y-1/2 h-12 w-12 text-2xl font-bold animate-in fade-in zoom-in duration-150`}
        title={label}
      >
        {arrow}
      </div>
    );
  }
  const icon = edge === "in" ? "+" : "−";
  const label = edge === "in" ? "детальнее" : "общий вид";
  return (
    <div
      className={`${common} left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 h-14 w-14 text-3xl font-bold animate-in fade-in zoom-in duration-150`}
      title={label}
    >
      {icon}
    </div>
  );
}
