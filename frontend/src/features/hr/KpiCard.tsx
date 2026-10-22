import { useQuery } from "@tanstack/react-query";
import { fetchMyKpi } from "@/api/hr";
import { CardSkeleton } from "@/components/Skeleton";
import Icon from "@/components/Icon";

/**
 * KPI смены: опыт за закрытые пункты, смены и поручения.
 *
 * В отличие от скрытых ачивок (`AchievementsCard`) карточка открыта всем: это
 * мотивация, а не надзор. Опыт считает сервер по правилам из админки, поэтому
 * здесь нет ни одного «веса» — только то, что пришло в ответе. Никаких
 * понижений и антизваний: звание растёт и не отнимается.
 */
export default function KpiCard() {
  const q = useQuery({ queryKey: ["hr-kpi-me"], queryFn: fetchMyKpi });

  if (q.isLoading) return <CardSkeleton />;

  // Ручка новая: живой бэкенд может её ещё не знать. Тогда карточки просто
  // нет — обещать прогресс, которого сервер не считает, нельзя.
  if (q.isError || !q.data) return null;

  const kpi = q.data;
  const winner = kpi.employee_of_week;
  const place = kpi.week_place;

  return (
    <section className="rounded-card bg-tg-secondary-bg/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-tg-text">Опыт смены</h2>
        <span className="rounded-full bg-tg-bg/60 px-2 py-0.5 text-xs text-tg-text">
          {kpi.rank.emoji} {kpi.rank.title}
        </span>
      </div>

      <div className="mt-2 flex items-end justify-between text-xs text-tg-hint">
        <span className="tabular-nums">{kpi.xp} XP</span>
        {kpi.next_rank ? (
          <span>
            до «{kpi.next_rank.title}» — {kpi.left} XP
          </span>
        ) : (
          <span>максимальное звание</span>
        )}
      </div>
      <div
        className="mt-1 h-1.5 overflow-hidden rounded-full bg-tg-bg/70"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={kpi.percent}
        aria-label="Прогресс до следующего звания"
      >
        <div
          className="h-full rounded-full bg-tg-button transition-[width]"
          style={{ width: `${kpi.percent}%` }}
        />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <Cell label="За неделю" value={`${kpi.week_xp} XP`} />
        <Cell
          label="Место в неделе"
          value={place ? `${place} из ${kpi.week_total}` : "—"}
        />
        <Cell label="Пунктов чек-листа" value={String(kpi.week_counts.checklist_items)} />
        <Cell label="Поручений закрыто" value={String(kpi.week_counts.tasks_done)} />
      </div>

      <div className="mt-3 rounded-tile bg-tg-bg/50 p-2 text-xs">
        {winner ? (
          <>
            <div className="text-tg-hint">Сотрудник недели</div>
            <div className="mt-0.5 text-tg-text">
              <Icon name="award" size={14} className="mr-1 inline-block align-[-2px]" />
              {winner.display_name}
              {winner.department ? ` · ${winner.department}` : ""} — {winner.xp} XP
            </div>
          </>
        ) : (
          <div className="text-tg-hint">
            Номинант появится, когда кто-то наберёт минимум опыта за неделю (
            {kpi.rules.min_xp_winner} XP).
          </div>
        )}
      </div>

      <p className="mt-2 text-xs text-tg-hint">
        Опыт дают закрытые пункты чек-листа, полностью закрытая смена и поручения.
        Вовремя закрытое поручение даёт надбавку.
      </p>
    </section>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-tile bg-tg-bg/50 p-2">
      <div className="text-tg-hint">{label}</div>
      <div className="tabular-nums text-tg-text">{value}</div>
    </div>
  );
}
