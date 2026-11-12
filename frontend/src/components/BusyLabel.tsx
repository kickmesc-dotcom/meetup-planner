import type { ReactNode } from "react";

import { Spinner } from "./Spinner";

/**
 * Подпись действия, пока запрос в пути.
 *
 * Зачем обёртка. В busy-кнопках спиннер и текст собирались вручную: где-то
 * текст менялся на «Сохраняем…», где-то кнопка просто бледнела. Одинаковый
 * вид в одном месте ещё и держит ширину: текст действия не исчезает, поэтому
 * кнопка не прыгает, а рядом появляется индикатор.
 */
export function BusyLabel({
  busy,
  children,
}: {
  busy: boolean;
  children: ReactNode;
}) {
  if (!busy) return <>{children}</>;
  return (
    <span className="inline-flex items-center justify-center gap-1.5">
      <Spinner size={12} />
      <span>{children}</span>
    </span>
  );
}
