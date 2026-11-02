/**
 * Витрина демо-данных (план, фаза 3, шаг 3.3).
 *
 * Зачем экран, если API демо уже было. Механизм `[BOT]` существовал год, но
 * нажимать его было негде: засеять пул, сгенерировать смены и снести следы
 * можно было только через ручки. На встрече с клиентом это значит «сейчас
 * подождите, я через консоль» — то есть витрины не было.
 *
 * Порядок на экране повторяет разговор: сначала «что вы увидите» (люди и
 * активность), потом три действия по одной кнопке, потом удаление. Так
 * demo показывается за минуты, а не за вечер.
 *
 * Что важно в тексте: демо не смешивается с боевыми данными (`[BOT]`-метка и
 * тумблер видимости), поэтому его можно включать в рабочей организации.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchDemoState,
  purgeDemo,
  seedDemoPool,
  setDemoVisible,
  simulateDemo,
  type HrDemoState,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import Icon, { InlineIcon } from "@/components/Icon";
import { Skeleton } from "@/components/Skeleton";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import SubScreen from "./SubScreen";
import { useTx } from "@/i18n";

interface Props {
  onBack: () => void;
}

export default function DemoScreen({ onBack }: Props) {
  const { tx } = useTx();
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["hr-demo"],
    queryFn: fetchDemoState,
    staleTime: 15_000,
    retry: false,
  });

  /** Демо живёт в ленте, отчётах и чек-листах — сбрасываем всё, что его читает. */
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["hr-demo"] });
    void qc.invalidateQueries({ queryKey: ["feed"] });
    void qc.invalidateQueries({ queryKey: ["admin-employees"] });
    void qc.invalidateQueries({ queryKey: ["team"] });
  };

  const seed = useMutation({
    mutationFn: seedDemoPool,
    onSuccess: async (out: HrDemoState) => {
      haptic("success");
      refresh();
      await showAlert(
        tx("Демо готово: {n} тестовых сотрудников из пакета «{industry}».", {
          n: out.employees.length,
          industry: out.industry_title,
        }),
      );
    },
    onError: async (e) => {
      haptic("error");
      await showAlert(humanizeApiError(e));
    },
  });

  const simulate = useMutation({
    mutationFn: () => simulateDemo(3),
    onSuccess: async (out: Record<string, number>) => {
      haptic("success");
      refresh();
      await showAlert(
        tx("Смены закрыты: чек-листов — {runs}, поручений — {tasks}.", {
          runs: out.checklist_runs ?? 0,
          tasks: out.tasks ?? 0,
        }),
      );
    },
    onError: async (e) => {
      haptic("error");
      await showAlert(humanizeApiError(e));
    },
  });

  const purge = useMutation({
    mutationFn: (deleteEmployees: boolean) => purgeDemo(deleteEmployees),
    onSuccess: async () => {
      haptic("success");
      refresh();
      await showAlert(tx("Следы демо удалены."));
    },
    onError: async (e) => {
      haptic("error");
      await showAlert(humanizeApiError(e));
    },
  });

  const visibility = useMutation({
    mutationFn: (visible: boolean) => setDemoVisible(visible),
    onSuccess: () => {
      haptic("light");
      refresh();
    },
    onError: async (e) => {
      haptic("error");
      await showAlert(humanizeApiError(e));
    },
  });

  const data = q.data;
  const busy =
    q.isPending ||
    seed.isPending ||
    simulate.isPending ||
    purge.isPending ||
    visibility.isPending;
  const people = data?.employees.length ?? 0;
  const activity = data?.activity;

  return (
    <SubScreen
      title={tx("Демо-данные")}
      subtitle={tx("Покажем на ваших данных за 5 минут")}
      onBack={onBack}
    >
      {q.isError && (
        <div className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
          <InlineIcon name="alert" />
          {humanizeApiError(q.error)}
        </div>
      )}

      {q.isPending && <Skeleton className="h-24 w-full" />}

      {data && (
        <>
          <section className="rounded-card bg-tg-secondary-bg/60 p-3 space-y-2">
            <div className="flex items-center gap-2">
              <Icon name="layout" size={18} className="text-tg-link" />
              <span className="text-sm font-semibold text-tg-text">
                {tx("Демо «{industry}»", { industry: data.industry_title })}
              </span>
            </div>
            <p className="text-xs text-tg-hint">
              {tx(
                "Тестовые сотрудники помечены «{prefix}» и не смешиваются с боевыми данными: их следы можно спрятать из ленты одним тумблером, а людей — удалить целиком.",
                { prefix: data.prefix },
              )}
            </p>
            <div className="flex flex-wrap gap-2 text-2xs text-tg-hint">
              <span className="rounded-tile bg-tg-secondary-bg px-2 py-0.5">
                {tx("Людей: {n}", { n: people })}
              </span>
              <span className="rounded-tile bg-tg-secondary-bg px-2 py-0.5">
                {tx("Чек-листов: {n}", { n: activity?.checklist_runs ?? 0 })}
              </span>
              <span className="rounded-tile bg-tg-secondary-bg px-2 py-0.5">
                {tx("Поручений: {n}", { n: activity?.tasks ?? 0 })}
              </span>
              <span className="rounded-tile bg-tg-secondary-bg px-2 py-0.5">
                {tx("Ответов: {n}", { n: activity?.feedback_answers ?? 0 })}
              </span>
            </div>
            {people > 0 && (
              <ul className="space-y-0.5">
                {data.employees.map((row) => (
                  <li
                    key={row.employee_id}
                    className="flex items-baseline justify-between gap-2 text-2xs text-tg-hint"
                  >
                    <span>{row.display_name}</span>
                    <span>
                      {row.department_name ?? tx("без подразделения")}
                      {row.badge ? ` · ${row.badge}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-card bg-tg-secondary-bg/40 p-3 space-y-2">
            <div className="text-2xs uppercase tracking-wide text-tg-hint">
              {tx("Что покажем")}
            </div>
            <p className="text-xs text-tg-hint">
              {tx(
                "Ленту смены, закрытые чек-листы, поручения в работе, опоздания и обратную связь. Состав — из отраслевого пакета, поэтому салон видит мастеров, а не поваров.",
              )}
            </p>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                haptic("light");
                seed.mutate();
              }}
              className="w-full rounded-tile bg-tg-link px-3 py-2 text-sm font-semibold text-white press disabled:opacity-50"
            >
              {people > 0
                ? tx("Обновить состав демо")
                : tx("Завести демо-сотрудников")}
            </button>
            <button
              type="button"
              disabled={busy || people === 0}
              onClick={() => {
                haptic("light");
                simulate.mutate();
              }}
              className="w-full rounded-tile bg-tg-secondary-bg px-3 py-2 text-xs text-tg-text press disabled:opacity-50"
            >
              {tx("Сгенерировать активность за 3 смены")}
            </button>
          </section>

          <section className="rounded-card bg-tg-secondary-bg/40 p-3 space-y-2">
            <div className="text-2xs uppercase tracking-wide text-tg-hint">
              {tx("Видимость и уборка")}
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                haptic("light");
                visibility.mutate(!data.visible);
              }}
              className="w-full rounded-tile bg-tg-secondary-bg px-3 py-2 text-xs text-tg-text press disabled:opacity-50"
            >
              {data.visible
                ? tx("Спрятать следы демо из ленты")
                : tx("Показать следы демо в ленте")}
            </button>
            <button
              type="button"
              disabled={busy || people === 0}
              onClick={async () => {
                const ok = await showConfirm(
                  tx(
                    "Удалить следы демо: чек-листы, поручения, фото и обратную связь? Сами тестовые люди останутся.",
                  ),
                );
                if (ok) purge.mutate(false);
              }}
              className="w-full rounded-tile bg-tg-secondary-bg px-3 py-2 text-xs text-tg-text press disabled:opacity-50"
            >
              {tx("Удалить только следы")}
            </button>
            <button
              type="button"
              disabled={busy || people === 0}
              onClick={async () => {
                const ok = await showConfirm(
                  tx(
                    "Удалить демо-сотрудников вместе с их активностью? Боевые данные не тронутся.",
                  ),
                );
                if (ok) purge.mutate(true);
              }}
              className="w-full rounded-tile bg-status-busy/10 px-3 py-2 text-xs text-status-busy press disabled:opacity-50"
            >
              {tx("Удалить демо-сотрудников")}
            </button>
          </section>
        </>
      )}
    </SubScreen>
  );
}
