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

interface SwitchProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  className?: string;
  /** Тактильная отдача при переключении (по умолчанию — да). */
  hapticOnChange?: boolean;
  /** GHG11(10): `sm` — вполовину меньше, для тихих «необязательных» настроек. */
  size?: "sm" | "md";
}

/**
 * DESIGN_SYSTEM §8: единый on/off-переключатель.
 *
 * Раньше был скопирован локально в 7 экранах (Profile, CalendarSettings,
 * BotReactions, MediaReactions, ScheduledPublications, Zaebal, WormMaster) —
 * каждая копия слегка отличалась. Теперь это единственный источник.
 *
 * `haptic("selection")` внутри по умолчанию — переключение всегда «отзывается»
 * одинаково на всех экранах. Отключается через `hapticOnChange={false}`.
 */
export function Switch({
  checked,
  onChange,
  disabled,
  className,
  hapticOnChange = true,
  size = "md",
}: SwitchProps) {
  // GHG11(10): `sm` — ровно вполовину визуально меньше (`h-4 w-8` против
  // `h-6 w-11`), для тихих настроек «хорошо иметь», которые не должны
  // выглядеть как рекомендованное действие.
  const small = size === "sm";
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => {
        if (hapticOnChange) haptic("selection");
        onChange(!checked);
      }}
      className={[
        "shrink-0 inline-flex items-center rounded-full transition-colors disabled:opacity-50",
        small ? "h-4 w-8" : "h-6 w-11",
        checked ? "bg-tg-button" : "bg-tg-hint/30",
        className ?? "",
      ].join(" ")}
      role="switch"
      aria-checked={checked}
    >
      <span
        className={[
          "inline-block transform rounded-full bg-white shadow transition-transform",
          small ? "h-3 w-3" : "h-5 w-5",
          checked
            ? small
              ? "translate-x-4"
              : "translate-x-5"
            : small
              ? "translate-x-0.5"
              : "translate-x-0.5",
        ].join(" ")}
      />
    </button>
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
