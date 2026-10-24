import { useQuery } from "@tanstack/react-query";
import { fetchAchievements } from "@/api/hr";
import Icon from "@/components/Icon";
import { useTx } from "@/i18n";
/**
 * SemiTaskBot: скрытый блок «личный прогресс» в профиле.
 *
 * По решению владельца ачивки — не витрина, а личный счётчик: он живёт внутри
 * профиля и пока показывается только руководителю и администратору. Поэтому
 * карточка не «прячет» себя на клиенте, а честно рисует то, что решил сервер:
 * при `visible=false` не рендерится вообще, поэтому обычный сотрудник не видит
 * ни заголовка, ни пустых полей.
 *
 * Сами ачивки привязаны к работе (закрытые поручения, рабочие дни, пункты
 * чек-листа) — шуточный контур в этот контур не входит.
 */
export default function AchievementsCard() {
  const { tx } = useTx();
  const q = useQuery({
    queryKey: ["hr-achievements"],
    queryFn: fetchAchievements,
  });

  if (!q.data?.visible) return null;

  const { awarded, stats, next_goals: goals } = q.data;

  return (
    <section className="rounded-card bg-tg-secondary-bg/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-tg-text">
          <Icon name="award" size={15} className="shrink-0 text-tg-link" />{tx("Личный прогресс")}</h2>
        <span className="text-xs text-tg-hint">
          {awarded.length ? tx("{count} шт.", { count: awarded.length }) : tx("пока пусто")}
        </span>
      </div>
      <p className="mt-1 text-xs text-tg-hint">{tx(
        "Счётчик для себя: он растёт от закрытых поручений и отработанных смен. Гостям и коллегам блок пока не виден.",
      )}</p>

      {awarded.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {awarded.map((a) => (
            <li
              key={a.code}
              className="flex items-center gap-1 rounded-full bg-tg-bg/60 px-2 py-1 text-xs text-tg-text"
            >
              <span aria-hidden>{a.emoji}</span>
              <span className="truncate">{a.title}</span>
            </li>
          ))}
        </ul>
      )}

      {goals.length > 0 && (
        <div className="mt-2 space-y-1">
          {goals.map((g) => (
            <div
              key={g.code}
              className="flex items-center justify-between gap-2 text-xs text-tg-hint"
            >
              <span className="truncate">
                <span aria-hidden>{g.emoji}</span> {g.title}
              </span>
              <span className="shrink-0 tabular-nums">
                {g.done}/{g.threshold}
              </span>
            </div>
          ))}
        </div>
      )}

      {Object.keys(stats).length > 0 && (
        <div className="mt-2 grid grid-cols-3 gap-1.5 text-center text-xs">
          <Stat label={tx("поручений")} value={stats.tasks_done ?? 0} />
          <Stat label={tx("рабочих дней")} value={stats.shift_days ?? 0} />
          <Stat label={tx("пунктов")} value={stats.checklist_items ?? 0} />
        </div>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-tile bg-tg-bg/50 p-2">
      <div className="text-sm font-semibold text-tg-text tabular-nums">
        {value}
      </div>
      <div className="text-tg-hint">{label}</div>
    </div>
  );
}
