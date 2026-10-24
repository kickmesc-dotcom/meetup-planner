import { useTx } from "@/i18n";

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
  tone,
  className = "",
}: {
  text: string | null | undefined;
  emoji?: string | null;
  /** Пометка тестового пула `[BOT]`. */
  demo?: boolean;
  /**
   * Цвет подразделения: плашка «Менеджер» становится овальной пилюлей в цвет
   * отдела. Без `tone` — нейтральная, как раньше.
   */
  tone?: { border: string; soft: string };
  className?: string;
}) {
  // Подпись — содержимое, которое завёл человек: заводские должности
  // переводятся (есть в словаре), свои остаются как есть.
  const { tx } = useTx();
  if (!text && !demo) return null;
  return (
    <span
      className={[
        "inline-flex max-w-full items-center gap-1 rounded-full px-2 py-0.5 align-middle text-2xs font-medium",
        tone ? "text-tg-text" : "bg-tg-bg/70 text-tg-hint",
        className,
      ].join(" ")}
      style={
        tone
          ? {
              backgroundColor: tone.soft,
              border: `1px solid ${tone.border}`,
            }
          : undefined
      }
    >
      {emoji && <span aria-hidden>{emoji}</span>}
      {text && <span className="truncate">{tx(text)}</span>}
      {demo && (
        // VISUAL_AUDIT P3.16: «BOT» — это подпись, а не состояние, поэтому
        // нейтральный фон: янтарный статусный цвет на плашке спорил с
        // настоящими статусами (выполнено/просрочено) на том же экране.
        <span className="shrink-0 rounded-full bg-tg-hint/15 px-1 text-tg-hint">
          BOT
        </span>
      )}
    </span>
  );
}
