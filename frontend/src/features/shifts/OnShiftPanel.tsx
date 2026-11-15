import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchOnShift, type OnShiftPerson, type OnShiftState } from "@/api/shifts";
import Icon from "@/components/Icon";
import { Skeleton } from "@/components/Skeleton";
import { useTx } from "@/i18n";

/**
 * «Сейчас на смене» — полоса над графиком.
 *
 * Зачем она, если есть сетка. Сетка отвечает «кто когда работает», но чтобы
 * ответить на вопрос «кто сейчас в зале», нужно сегодняшний столбец и текущее
 * время в голове. Ночью, в спешке, это не считается. Полоса даёт готовый ответ:
 * кто в смене, до скольки, кто ещё придёт.
 *
 * Обновление раз в минуту, а не по каждому кадру: минута — это точность, с
 * которой меняется состояние смены, а лишний запрос каждые пять секунд не
 * стоит ничего, кроме батареи.
 *
 * Если запрос не удался, панель просто не рисуется: график от неё не зависит,
 * и красная плашка над ним мешала бы работать.
 */
export default function OnShiftPanel() {
  const { tx } = useTx();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["on-shift"],
    queryFn: fetchOnShift,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // Причину смены состояния видно только по часам: без этого панель «застыла»
  // бы до следующего открытия экрана у человека, который её не закрывает.
  useEffect(() => {
    const timer = window.setInterval(() => {
      void qc.invalidateQueries({ queryKey: ["on-shift"] });
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [qc]);

  if (q.isLoading) {
    return (
      <div className="border-b border-tg-secondary-bg px-3 py-2" aria-busy="true">
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="mt-2 h-6 w-2/3" />
      </div>
    );
  }
  if (q.isError || !q.data) return null;

  const items = q.data.items;
  if (items.length === 0) return null;

  const groups = new Map<string, OnShiftPerson[]>();
  for (const person of items) {
    const key = person.department_name ?? tx("Без отдела");
    const list = groups.get(key) ?? [];
    list.push(person);
    groups.set(key, list);
  }

  return (
    <section
      aria-labelledby="on-shift-title"
      data-testid="on-shift-panel"
      className="border-b border-tg-secondary-bg px-3 py-2"
    >
      <h2
        id="on-shift-title"
        className="flex items-center gap-1.5 text-xs font-semibold text-tg-text"
      >
        <Icon name="team" size={14} className="text-tg-hint" />
        {tx("Сейчас на смене")}
        <span className="rounded-full bg-status-free/15 px-1.5 py-0.5 text-2xs font-medium text-status-free">
          {tx("{count} в смене", { count: q.data.on_shift })}
        </span>
      </h2>

      <div className="mt-1.5 space-y-1.5">
        {[...groups].map(([department, people]) => (
          <div key={department}>
            <div className="text-2xs uppercase tracking-wide text-tg-hint">
              {department}
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {people.map((person) => (
                <span
                  key={person.employee_id}
                  title={`${person.display_name}${
                    person.ends_at ? ` · ${tx("до {time}", { time: person.ends_at })}` : ""
                  }`}
                  className={[
                    "rounded-full px-2 py-1 text-2xs",
                    CHIP_CLASS[person.state],
                  ].join(" ")}
                >
                  {person.display_name}
                  {person.ends_at ? ` · ${tx("до {time}", { time: person.ends_at })}` : ""}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

const CHIP_CLASS: Record<OnShiftState, string> = {
  on_shift: "bg-status-free/15 text-status-free",
  upcoming: "bg-tg-secondary-bg text-tg-text",
  planned: "bg-tg-secondary-bg text-tg-hint",
  finished: "bg-tg-secondary-bg/50 text-tg-hint line-through",
};
