/**
 * KPI смены (админ): веса опыта и недельный рейтинг.
 *
 * Раньше игровой экран админки крутил шуточный контур (чухан/лох/червь): там
 * награждали за случайность. Здесь наоборот — админ настраивает, сколько стоит
 * реальная работа, и видит, кто на этой неделе её сделал больше всех.
 *
 * Числа правятся по одному и сохраняются сразу (PUT с частичным телом):
 * «сохранить всё» здесь опасно — админ может передумать на середине.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchKpiOverview,
  updateKpiRules,
  type HrKpiRules,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import { ListSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

const FIELDS: { key: keyof HrKpiRules; label: string; hint: string }[] = [
  {
    key: "xp_checklist_item",
    label: "Пункт чек-листа",
    hint: "За каждый отмеченный пункт смены",
  },
  {
    key: "xp_shift_done",
    label: "Закрытая смена",
    hint: "Когда все обязательные пункты закрыты",
  },
  { key: "xp_task", label: "Поручение", hint: "За закрытое поручение АУП" },
  {
    key: "xp_on_time",
    label: "В срок",
    hint: "Надбавка, если поручение закрыто до дедлайна",
  },
  {
    key: "min_xp_winner",
    label: "Минимум для номинации",
    hint: "Сколько опыта нужно за неделю, чтобы попасть в номинанты",
  },
];

export default function KpiScreen({ onBack }: Props) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "kpi"],
    queryFn: fetchKpiOverview,
    staleTime: 30_000,
  });

  const mut = useMutation({
    mutationFn: (patch: Partial<HrKpiRules>) => updateKpiRules(patch),
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["admin", "kpi"] });
      // Личная карточка считает тот же опыт — иначе она покажет старые числа.
      void qc.invalidateQueries({ queryKey: ["hr-kpi-me"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const rules = q.data?.rules;
  const winner = q.data?.employee_of_week;
  const board = (q.data?.leaderboard ?? []).filter((row) => row.xp > 0);

  return (
    <SubScreen
      title="🏅 KPI смены"
      subtitle="Опыт за работу, рейтинг недели"
      onBack={onBack}
    >
      {q.isError && (
        <div className="rounded-lg bg-status-busy/10 p-2 text-xs text-status-busy">
          ⚠ {humanizeApiError(q.error)}
        </div>
      )}
      {q.isLoading && <ListSkeleton rows={4} />}

      {rules && (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
          <div className="text-sm font-semibold text-tg-text">Сколько стоит работа</div>
          <div className="text-[11px] text-tg-hint">
            Веса действуют сразу: опыт пересчитывается из уже записанных смен и
            поручений, передеплой не нужен.
          </div>
          {FIELDS.map((field) => (
            <label
              key={field.key}
              className="flex items-center justify-between gap-3 rounded-lg bg-tg-bg/50 p-2"
            >
              <span className="min-w-0">
                <span className="block text-xs text-tg-text">{field.label}</span>
                <span className="block text-[10px] text-tg-hint">{field.hint}</span>
              </span>
              <input
                type="number"
                inputMode="numeric"
                min={0}
                max={field.key === "min_xp_winner" ? 1000 : 100}
                defaultValue={rules[field.key]}
                disabled={mut.isPending}
                onBlur={(e) => {
                  const next = Number(e.target.value);
                  if (!Number.isFinite(next) || next === rules[field.key]) return;
                  mut.mutate({ [field.key]: Math.max(0, Math.round(next)) });
                }}
                className="w-16 shrink-0 rounded-md bg-tg-bg px-2 py-1 text-right text-sm tabular-nums text-tg-text"
                aria-label={field.label}
              />
            </label>
          ))}
          {mut.isPending && (
            <div className="text-[11px] text-tg-hint">Сохраняем…</div>
          )}
        </section>
      )}

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-sm font-semibold text-tg-text">Неделя</div>
        {q.data && (
          <div className="text-[11px] text-tg-hint">
            {q.data.week_start} — {q.data.week_end} · пн–вс
          </div>
        )}
        <div className="rounded-lg bg-tg-bg/50 p-2 text-[11px]">
          {winner ? (
            <>
              <div className="text-tg-hint">Сотрудник недели</div>
              <div className="mt-0.5 text-tg-text">
                🏅 {winner.display_name}
                {winner.department ? ` · ${winner.department}` : ""} — {winner.xp} XP,{" "}
                {winner.tasks_done} поруч.
              </div>
            </>
          ) : (
            <div className="text-tg-hint">
              Пока никто не набрал минимум опыта — номинация пустая. Это нормально
              в начале недели.
            </div>
          )}
        </div>

        {board.length === 0 && !q.isLoading ? (
          <div className="text-[11px] text-tg-hint">
            За эту неделю ещё нет закрытых смен и поручений.
          </div>
        ) : (
          <ul className="space-y-1">
            {board.slice(0, 10).map((row) => (
              <li
                key={row.employee_id}
                className="flex items-center gap-2 rounded-lg bg-tg-bg/40 px-2 py-1.5 text-xs"
              >
                <span className="w-5 shrink-0 text-right tabular-nums text-tg-hint">
                  {row.place}
                </span>
                <span className="min-w-0 flex-1 truncate text-tg-text">
                  {row.display_name}
                  {row.department ? (
                    <span className="text-tg-hint"> · {row.department}</span>
                  ) : null}
                </span>
                <span className="shrink-0 tabular-nums text-tg-text">{row.xp} XP</span>
              </li>
            ))}
          </ul>
        )}
        <div className="text-[10px] text-tg-hint">
          Тестовый пул `[BOT]` в рейтинг не попадает: звание — для живых людей.
        </div>
      </section>
    </SubScreen>
  );
}
