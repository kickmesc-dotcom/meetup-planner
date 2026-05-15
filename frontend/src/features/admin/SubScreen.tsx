import { ReactNode } from "react";
import { haptic } from "@/tg/webapp";

interface Props {
  title: string;
  subtitle?: string;
  onBack: () => void;
  children: ReactNode;
}

export default function SubScreen({ title, subtitle, onBack, children }: Props) {
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-tg-secondary-bg">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onBack();
          }}
          className="min-h-9 min-w-9 rounded-md bg-tg-secondary-bg/60 px-2 text-sm text-tg-link active:scale-95 transition-transform"
          aria-label="Назад"
        >
          ←
        </button>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold truncate">{title}</div>
          {subtitle && (
            <div className="text-[11px] text-tg-hint truncate">{subtitle}</div>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-4">{children}</div>
    </div>
  );
}
