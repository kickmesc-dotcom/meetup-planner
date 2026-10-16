/**
 * SemiTaskBot: плашка «должность / звание» рядом с именем.
 *
 * Плашку ставит админ (или сид владельцев проекта), она ничего не разрешает — это
 * только подпись: «🛠 Разработчик», «🧭 Управляющий», «🍳 Су-шеф». Поэтому
 * компонент предельно простой и без логики прав.
 */
export default function Badge({
  text,
  emoji,
  demo,
  className = "",
}: {
  text: string | null | undefined;
  emoji?: string | null;
  /** Пометка тестового пула `[BOT]`. */
  demo?: boolean;
  className?: string;
}) {
  if (!text && !demo) return null;
  return (
    <span
      className={[
        "inline-flex max-w-full items-center gap-1 rounded-full bg-tg-bg/70 px-2 py-0.5 align-middle text-[10px] font-medium text-tg-hint",
        className,
      ].join(" ")}
    >
      {emoji && <span aria-hidden>{emoji}</span>}
      {text && <span className="truncate">{text}</span>}
      {demo && (
        <span className="shrink-0 rounded-full bg-status-maybe/20 px-1 text-status-maybe">
          BOT
        </span>
      )}
    </span>
  );
}
