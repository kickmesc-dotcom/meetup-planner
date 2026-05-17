interface SpinnerProps {
  size?: number;
  className?: string;
}

/**
 * Лёгкий CSS-only spinner на currentColor. Используется внутри кнопки рядом
 * с текстом «Сохраняем…» и т.п., чтобы pending-состояние было визуально
 * заметно (U5).
 */
export function Spinner({ size = 14, className }: SpinnerProps) {
  return (
    <span
      className={["inline-block align-[-2px] animate-spin", className ?? ""].join(" ")}
      style={{
        width: size,
        height: size,
        border: "2px solid currentColor",
        borderRightColor: "transparent",
        borderRadius: "50%",
        opacity: 0.85,
      }}
      aria-hidden
    />
  );
}
