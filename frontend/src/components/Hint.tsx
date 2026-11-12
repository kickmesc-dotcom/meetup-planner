import type { ReactNode } from "react";

/**
 * Подсказка под группой полей или кнопок.
 *
 * Зачем компонент. Подсказка поля живёт в `FormField.hint` — там она связана
 * с input через `aria-describedby`. Но у группы (дни недели, роли, пояснение
 * блока) поля нет, и такой текст рисовали руками: где-то `text-xs`, где-то
 * `text-2xs`, с разным отступом. Один компонент держит вид подсказки и не
 * даёт скопировать её внутрь `FormField`, где она задвоится.
 *
 * `size="xs"` — для описания секции или шага: это не мелкая сноска под
 * полем, а вводный абзац, и 12 px читаются заметно легче.
 */
export default function Hint({
  children,
  className,
  size = "2xs",
}: {
  children: ReactNode;
  className?: string;
  size?: "2xs" | "xs";
}) {
  const sizeClass = size === "xs" ? "text-xs" : "text-2xs";
  return (
    <p
      className={[sizeClass, "text-tg-hint", className ?? "mt-1"]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </p>
  );
}
