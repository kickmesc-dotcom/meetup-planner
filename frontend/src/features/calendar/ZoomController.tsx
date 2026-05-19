import { useUI, ZOOM_LABELS, type ZoomLevel } from "@/store/ui";
import { haptic } from "@/tg/webapp";

const COMPACT_ORDER: ZoomLevel[] = [
  "hour",
  "day",
  "week",
  "month",
  "threeMonths",
  "sixMonths",
  "year",
  "allYears",
];

export default function ZoomController() {
  const zoom = useUI((s) => s.zoom);
  const setZoom = useUI((s) => s.setZoom);

  return (
    <div className="px-3 py-2 border-b border-tg-secondary-bg overflow-x-auto">
      <div className="flex bg-tg-secondary-bg rounded-xl p-0.5 gap-0.5 w-max mx-auto">
        {COMPACT_ORDER.map((z) => (
          <button
            key={z}
            type="button"
            onClick={() => {
              haptic("light");
              setZoom(z);
            }}
            className={[
              "px-2.5 py-1 text-[11px] rounded-lg transition-colors whitespace-nowrap",
              z === zoom ? "bg-tg-button text-tg-button-text font-medium" : "text-tg-hint",
            ].join(" ")}
            aria-pressed={z === zoom}
          >
            {ZOOM_LABELS[z]}
          </button>
        ))}
      </div>
    </div>
  );
}

