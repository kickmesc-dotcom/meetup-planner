/**
 * Единый прогресс-бар для опыта и прогресса ачивок.
 *
 * Зачем отдельный компонент. Раньше в списке ачивок прогресс рисовался текстом
 * «12 → 25», а уровень — своей шкалой в `RankPlaque`. Продакшн-фидбек: «число,
 * стрелка вправо и снова число — максимально неочевидно, если это прогресс».
 * Поэтому правило одно: **отношение показывается полосой и всегда подписано
 * `X/Y`**. Никаких стрелок и голых пар чисел.
 */
interface Props {
  /** Сколько набрано. */
  value: number;
  /** Сколько нужно. 0 или меньше — полоса считается заполненной. */
  total: number;
  /** Подпись слева (что за прогресс). */
  label?: string;
  /** Что показать перед `X/Y` справа — например «до юбилея». */
  hint?: string;
  /** Чем заполнять: тёплый акцент или нейтральный. */
  tone?: "brand" | "muted";
  /** Компактный вариант для строк списка. */
  size?: "sm" | "md";
  className?: string;
}

export default function ProgressBar({
  value,
  total,
  label,
  hint,
  tone = "brand",
  size = "md",
  className = "",
}: Props) {
  const safeValue = Math.max(0, value);
  const pct =
    total > 0 ? Math.min(100, Math.round((safeValue / total) * 100)) : 100;
  const height = size === "sm" ? "h-1.5" : "h-2";
  const fill = tone === "brand" ? "bg-tg-button" : "bg-tg-hint/60";

  return (
    <div className={["w-full", className].join(" ")}>
      {(label || hint) && (
        <div className="mb-1 flex items-baseline justify-between gap-2 text-[11px] text-tg-hint">
          <span className="min-w-0 truncate">{label}</span>
          <span className="shrink-0 tabular-nums">
            {hint ? `${hint} ` : ""}
            {safeValue}/{total}
          </span>
        </div>
      )}
      <div
        className={[
          "w-full overflow-hidden rounded-full bg-tg-bg/60",
          height,
        ].join(" ")}
        role="progressbar"
        aria-valuenow={safeValue}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-label={label ?? `${safeValue} из ${total}`}
      >
        <div
          className={["h-full rounded-full transition-[width] duration-300", fill].join(" ")}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/** Полоса в одну строку: подпись слева, `X/Y` сразу за полосой. Для списков. */
export function InlineProgress({
  value,
  total,
  className = "",
}: {
  value: number;
  total: number;
  className?: string;
}) {
  const safeValue = Math.max(0, value);
  const pct = total > 0 ? Math.min(100, Math.round((safeValue / total) * 100)) : 100;
  return (
    <div className={["flex items-center gap-2", className].join(" ")}>
      <div
        className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-tg-bg/60"
        role="progressbar"
        aria-valuenow={safeValue}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-label={`${safeValue} из ${total}`}
      >
        <div
          className="h-full rounded-full bg-tg-button transition-[width] duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="shrink-0 text-[11px] tabular-nums text-tg-hint">
        {safeValue}/{total}
      </span>
    </div>
  );
}
