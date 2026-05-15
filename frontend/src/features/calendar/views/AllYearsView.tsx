import { isThisYear } from "date-fns";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";

interface Props {
  anchor: Date;
}

/** Десятилетие вокруг anchor — 10 кнопок-годов. Тап → zoom=year. */
export default function AllYearsView({ anchor }: Props) {
  const setZoom = useUI((s) => s.setZoom);
  const setAnchor = useUI((s) => s.setAnchorDate);

  const yr = anchor.getFullYear();
  const decadeStart = yr - (yr % 10);
  const years = Array.from({ length: 10 }, (_, i) => decadeStart + i);

  const onYearTap = (y: number) => {
    haptic("light");
    setAnchor(new Date(y, anchor.getMonth(), 1));
    setZoom("year");
  };

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {years.map((y) => {
          const current = isThisYear(new Date(y, 6, 1));
          return (
            <button
              key={y}
              type="button"
              onClick={() => onYearTap(y)}
              className={[
                "aspect-[3/2] rounded-2xl flex items-center justify-center text-2xl font-semibold transition-transform active:scale-95",
                current
                  ? "bg-tg-button text-tg-button-text"
                  : "bg-tg-secondary-bg/60 text-tg-text",
                y === yr && !current ? "ring-2 ring-tg-link" : "",
              ].join(" ")}
            >
              {y}
            </button>
          );
        })}
      </div>
    </div>
  );
}
