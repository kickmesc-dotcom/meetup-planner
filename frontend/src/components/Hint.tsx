import type { ReactNode } from "react";

/**
 * Подсказка под группой полей или кнопок.
 *
 * Зачем компонент. Подсказка поля живёт в `FormField.hint` — там она связана
 * с input через `aria-describedby`. Но у группы (дни недели, роли, пояснение
 * блока) поля нет, и такой текст рисовали руками: где-то `text-xs`, где-то
 * `text-2xs`, с разным отступом. Один компонент держит вид подсказки и не
 * даёт скопировать её внутрь `FormField`, где она задвоится.
 */
export default function Hint({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <p className={["mt-1 text-2xs text-tg-hint", className].filter(Boolean).join(" ")}>
      {children}
    </p>
  );
}
