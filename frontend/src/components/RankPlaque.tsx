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

/**
 * Шкала прогресса уровня живёт в `components/ProgressBar.tsx`.
 *
 * Раньше она была отдельным экспортом здесь, а в списке ачивок прогресс рисовался
 * текстом — из-за этого одно и то же отношение выглядело по-разному в двух
 * местах одного экрана. Теперь полоса одна на весь фронт.
 */
