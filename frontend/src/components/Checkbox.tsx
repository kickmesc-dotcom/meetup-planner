import { haptic } from "@/tg/webapp";

interface CheckboxProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label?: string;
  size?: "sm" | "md";
  className?: string;
}

/**
 * Унифицированный чекбокс на CSS-классе .chk-tg.
 * Idle — рамка tg-hint/40; checked — заливка tg-link с белой галкой.
 * Контраст WCAG AA. Включён в styles.css.
 */
export function Checkbox({
  checked,
  onChange,
  disabled,
  label,
  size = "md",
  className,
}: CheckboxProps) {
  const sizeCls = size === "sm" ? "w-4 h-4 rounded-[5px]" : "";
  const inner = (
    <input
      type="checkbox"
      checked={checked}
      disabled={disabled}
      onChange={(e) => {
        haptic("selection");
        onChange(e.target.checked);
      }}
      className={["chk-tg", sizeCls, className ?? ""].join(" ")}
    />
  );
  if (!label) return inner;
  return (
    <label className="flex items-center gap-1.5 text-[11px] text-tg-hint cursor-pointer">
      {inner}
      <span>{label}</span>
    </label>
  );
}

interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label?: string;
  /** Подсветка строки активным фоном. */
  highlight?: boolean;
}

/**
 * Унифицированный toggle-slider (.tgl-tg). Используется для on/off настроек.
 * Если передан label — рендерится строкой с активной/неактивной подсветкой.
 */
export function Toggle({
  checked,
  onChange,
  disabled,
  label,
  highlight = true,
}: ToggleProps) {
  const input = (
    <input
      type="checkbox"
      checked={checked}
      disabled={disabled}
      onChange={(e) => {
        haptic("selection");
        onChange(e.target.checked);
      }}
      className="tgl-tg"
    />
  );
  if (!label) return input;
  return (
    <label
      className={`flex items-center justify-between gap-2 rounded-lg px-2 py-2 transition-colors cursor-pointer ${
        highlight && checked ? "bg-status-free/10" : "bg-tg-bg/30"
      }`}
    >
      <span className="text-sm text-tg-text">{label}</span>
      {input}
    </label>
  );
}
