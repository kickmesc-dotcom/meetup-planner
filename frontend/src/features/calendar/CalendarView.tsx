import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDrag, usePinch } from "@use-gesture/react";
import { fetchRanges } from "@/api/availability";
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

  const win = useMemo(() => windowForZoom(zoom, anchor), [zoom, anchor]);

  const ranges = useQuery({
    queryKey: ["ranges", win.start.toISOString(), win.end.toISOString()],
    queryFn: () => fetchRanges(win.start, win.end),
    staleTime: 15_000,
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
  const isPending = ranges.isPending;

  let body: React.ReactNode = null;
  if (zoom === "hour") {
    body = <HoursView day={win.start} users={users} meId={meId} ranges={data} />;
  } else if (isStripZoom(zoom)) {
    const span = zoom === "day" ? 1 : zoom === "week" ? 7 : 14;
    body = (
      <StripView
        windowStart={win.start}
        span={span}
        users={users}
        meId={meId}
        ranges={data}
        isPending={isPending}
      />
    );
  } else if (isMonthGridZoom(zoom)) {
    const months = zoom === "month" ? 1 : zoom === "threeMonths" ? 3 : 6;
    body = <MonthView months={months} anchor={anchor} ranges={data} users={users} />;
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
      <NavBar />
      <ZoomController />
      {body}
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
