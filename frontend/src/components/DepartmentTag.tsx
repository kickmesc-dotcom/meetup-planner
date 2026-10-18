/**
 * Тег подразделения рядом с именем сотрудника.
 *
 * В списках на 60 человек без него не видно, кто из какого отдела: имя есть, а
 * принадлежность приходится вспоминать. Тег маленький и не спорит с бейджем
 * должности — у отдела свой цвет фона, у должности свой Badge.
 */
export default function DepartmentTag({
  name,
  emoji,
  className = "",
}: {
  name: string | null | undefined;
  emoji?: string | null;
  className?: string;
}) {
  if (!name) return null;
  return (
    <span
      className={[
        "inline-flex max-w-full items-center gap-1 rounded-full bg-tg-bg/70 px-1.5 py-0.5 text-[10px] leading-none text-tg-hint",
        className,
      ].join(" ")}
      title={name}
    >
      {emoji ? <span aria-hidden>{emoji}</span> : null}
      <span className="truncate">{name}</span>
    </span>
  );
}
