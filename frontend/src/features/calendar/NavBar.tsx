import { isToday, startOfDay } from "date-fns";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";
import { zoomTitle } from "./dateUtils";

export default function NavBar() {
  const zoom = useUI((s) => s.zoom);
  const anchor = useUI((s) => s.anchorDate);
  const shift = useUI((s) => s.shiftAnchor);
  const goToday = useUI((s) => s.goToday);

  const today = isToday(startOfDay(anchor));

  return (
    <div className="flex items-center gap-2 px-3 py-2 border-b border-tg-secondary-bg bg-tg-bg">
      <button
        type="button"
        onClick={() => {
          haptic("light");
          shift(-1);
        }}
        className="w-9 h-9 flex items-center justify-center rounded-xl bg-tg-secondary-bg text-tg-text active:scale-95 transition-transform"
        aria-label="назад"
      >
        ‹
      </button>
      <div className="flex-1 text-center">
        <div className="text-sm font-semibold leading-tight">{zoomTitle(zoom, anchor)}</div>
        {!today && (
          <button
            type="button"
            onClick={() => {
              haptic("light");
              goToday();
            }}
            className="text-[11px] text-tg-link underline-offset-2 hover:underline"
          >
            к сегодня
          </button>
        )}
      </div>
      <button
        type="button"
        onClick={() => {
          haptic("light");
          shift(1);
        }}
        className="w-9 h-9 flex items-center justify-center rounded-xl bg-tg-secondary-bg text-tg-text active:scale-95 transition-transform"
        aria-label="вперёд"
      >
        ›
      </button>
    </div>
  );
}
