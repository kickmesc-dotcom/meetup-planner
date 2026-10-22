import Icon from "@/components/Icon";

/**
 * Индикатор раскрытия списка (VISUAL_AUDIT P1.4, полировка).
 *
 * Раньше в списках стояли текстовые `▸` / `▾` / `▼` / `▶`: это символы шрифта,
 * поэтому они зависят от гарнитуры, не совпадают по толщине с остальными
 * иконками и разъезжаются по базовой линии рядом с текстом. Здесь один
 * SVG-шеврон, который поворачивается на 90° при раскрытии — и одинаково
 * выглядит на Windows, iOS и Android.
 *
 * Иконка декоративная: состояние уже объявлено через `aria-expanded` на кнопке,
 * иначе скринридер читал бы «треугольник вниз».
 */
export default function ChevronToggle({
  open,
  size = 14,
  className = "",
}: {
  open: boolean;
  size?: number;
  className?: string;
}) {
  return (
    <Icon
      name="chevron"
      size={size}
      className={[
        "shrink-0 transition-transform duration-150 motion-reduce:transition-none",
        open ? "rotate-90" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    />
  );
}
