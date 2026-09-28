/**
 * GHG10 Э3.1: плашка ранга — цветной фон + контрастный текст.
 *
 * Задание: «при размещении ранга в профиле нужно обеспечить читаемость любого
 * сочетания». Ранг НЕЛЬЗЯ рисовать цветным текстом на произвольном фоне: цвета
 * рангов идут от светло-серого к золотому, и любой фиксированный цвет текста
 * где-то провалится (белый на светлом, чёрный на тёмном). Поэтому ранг —
 * «печать»: фон = цвет ранга, а цвет текста выбирается по контрасту.
 */

/**
 * Цвет текста поверх плашки: считаем относительную яркость (WCAG) и берём
 * вариант с большим контрастом. Так светло-серый (#9ca3af) и розовый
 * (#ec4899) получают тёмный текст, а красный/синий — белый.
 */
export function plaqueTextColor(hex: string): string {
  const c = hex.replace("#", "");
  if (c.length !== 6) return "#ffffff";
  const channel = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  const r = channel(parseInt(c.slice(0, 2), 16));
  const g = channel(parseInt(c.slice(2, 4), 16));
  const b = channel(parseInt(c.slice(4, 6), 16));
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const contrastWhite = 1.05 / (luminance + 0.05);
  const contrastBlack = (luminance + 0.05) / 0.05;
  return contrastWhite >= contrastBlack ? "#ffffff" : "#111827";
}

interface Props {
  hex: string;
  bold?: boolean;
  children: React.ReactNode;
  title?: string;
}

export default function RankPlaque({ hex, bold, children, title }: Props) {
  return (
    <span
      title={title}
      className={[
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs leading-tight",
        bold ? "font-bold" : "font-semibold",
      ].join(" ")}
      style={{ background: hex, color: plaqueTextColor(hex) }}
    >
      {children}
    </span>
  );
}

/** Шкала прогресса уровня. На максимуме заменяется счётчиком престижа (Э3.3). */
export function RankBar({
  value,
  total,
  label,
}: {
  value: number;
  total: number;
  label: string;
}) {
  const pct = total > 0 ? Math.min(100, Math.round((value / total) * 100)) : 100;
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-[11px] text-tg-hint">
        <span>{label}</span>
        <span className="tabular-nums">
          {value}/{total}
        </span>
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-tg-bg/60"
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={total}
      >
        <div
          className="h-full rounded-full bg-tg-button transition-[width] duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
