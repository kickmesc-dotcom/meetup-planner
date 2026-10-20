import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchDemoState,
  purgeDemo,
  seedDemoPool,
  setDemoVisible,
  simulateDemo,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton } from "@/components/Skeleton";
import Badge from "@/features/hr/Badge";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";

/**
 * SemiTaskBot: админский экран тестового пула `[BOT]`.
 *
 * Пул изображает жизнь смены (чек-листы, поручения, обратная связь), поэтому его
 * надо уметь мгновенно убрать с глаз: один тумблер прячет следы из ленты, списков
 * и отчётов, а две отдельные кнопки сносят данные — сначала только активность,
 * потом (если тестовые люди больше не нужны) самих сотрудников с их `users`.
 *
 * Удаление нарочно НЕ тумблер: обратной операции нет, поэтому спрашиваем
 * подтверждение и предупреждаем текстом, что именно уйдёт.
 */
export default function HrDemoPanel({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["hr-demo"], queryFn: fetchDemoState });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["hr-demo"] });
    void qc.invalidateQueries({ queryKey: ["hr-feed"] });
    void qc.invalidateQueries({ queryKey: ["hr-tasks"] });
  };

  const toggle = useMutation({
    mutationFn: (visible: boolean) => setDemoVisible(visible),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-demo"], data);
      invalidate();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const seed = useMutation({
    mutationFn: seedDemoPool,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-demo"], data);
      invalidate();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const simulate = useMutation({
    mutationFn: () => simulateDemo(3),
    onSuccess: (counts) => {
      haptic("success");
      invalidate();
      void showAlert(
        `Сгенерировали: смен ${counts.checklist_runs ?? 0}, поручений ${counts.tasks ?? 0}.`,
      );
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const purge = useMutation({
    mutationFn: (deleteEmployees: boolean) => purgeDemo(deleteEmployees),
    onSuccess: () => {
      haptic("warning");
      invalidate();
      void showAlert("Следы тестового пула удалены.");
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const busy = toggle.isPending || seed.isPending || simulate.isPending || purge.isPending;
  const data = q.data;

  return (
    <div className="absolute inset-0 z-30 flex flex-col bg-tg-bg">
      <header className="flex items-center gap-3 border-b border-tg-secondary-bg py-3 pl-4 pr-3">
        <div className="min-w-0 flex-1">
          <div className="text-base font-medium text-tg-text">🧪 Тестовый пул</div>
          <div className="text-xs text-tg-hint">
            Симуляторы работы с префиксом {data?.prefix ?? "[BOT]"}
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onClose();
          }}
          className="min-h-9 rounded-lg bg-tg-secondary-bg px-3 text-xs text-tg-text"
        >
          Закрыть
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {q.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}
        {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}

        {data && (
          <>
            <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-semibold text-tg-text">Следы пула</div>
                <span
                  className={[
                    "rounded-full px-2 py-0.5 text-xs",
                    data.visible
                      ? "bg-status-free/20 text-status-free"
                      : "bg-status-busy/20 text-status-busy",
                  ].join(" ")}
                >
                  {data.visible ? "👁 видны" : "🙈 скрыты"}
                </span>
              </div>
              <p className="mt-1 text-xs text-tg-hint">
                Тумблер прячет пул из ленты, списков и отчётов, не удаляя данные.
                Один тап — и боевая картина чистая.
              </p>
              <button
                type="button"
                disabled={busy}
                aria-pressed={data.visible}
                onClick={() => {
                  haptic("selection");
                  toggle.mutate(!data.visible);
                }}
                className="mt-2 min-h-11 w-full rounded-lg bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
              >
                {data.visible ? "🙈 Скрыть следы" : "👁 Показать следы"}
              </button>
            </section>

            <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
              <div className="text-sm font-semibold text-tg-text">
                Сотрудники пула: {data.employees.length}
              </div>
              <div className="mt-2 space-y-1">
                {data.employees.length === 0 && (
                  <div className="text-xs text-tg-hint">Пул не заведён.</div>
                )}
                {data.employees.map((e) => (
                  <div key={e.employee_id} className="flex items-center gap-2 text-xs">
                    <span className="min-w-0 flex-1 truncate text-tg-text">
                      {e.display_name}
                    </span>
                    <Badge text={e.badge} emoji={e.badge_emoji} />
                    <span className="shrink-0 text-tg-hint">
                      {e.department_name ?? "—"}
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
                <Metric label="Смен" value={data.activity.checklist_runs} />
                <Metric label="Поручений" value={data.activity.tasks} />
                <Metric label="Ответов ОС" value={data.activity.feedback_answers} />
              </div>
              <div className="mt-3 space-y-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    haptic("light");
                    seed.mutate();
                  }}
                  className="min-h-10 w-full rounded-lg bg-tg-secondary-bg text-xs font-medium text-tg-text disabled:opacity-50"
                >
                  🆕 Завести пул
                </button>
                <button
                  type="button"
                  disabled={busy || data.employees.length === 0}
                  onClick={() => {
                    haptic("light");
                    simulate.mutate();
                  }}
                  className="min-h-10 w-full rounded-lg bg-tg-secondary-bg text-xs font-medium text-tg-text disabled:opacity-50"
                >
                  ▶️ Симулировать 3 смены
                </button>
              </div>
            </section>

            <section className="rounded-xl border border-status-busy/30 p-3">
              <div className="text-sm font-semibold text-tg-text">Удаление</div>
              <p className="mt-1 text-xs text-tg-hint">
                Обратной операции нет. «Активность» убирает смены, поручения и
                ответы, а «вместе с сотрудниками» удаляет и самих тестовых людей
                с их строками в базе.
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  const ok = await showConfirm(
                    "Снести всю активность тестового пула? Сотрудники останутся.",
                  );
                  if (ok) purge.mutate(false);
                }}
                className="mt-2 min-h-10 w-full rounded-lg bg-status-busy/15 text-xs font-medium text-status-busy disabled:opacity-50"
              >
                🧹 Снести только активность
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  const ok = await showConfirm(
                    "Удалить тестовых сотрудников вместе со всей их активностью?",
                  );
                  if (ok) purge.mutate(true);
                }}
                className="mt-2 min-h-10 w-full rounded-lg bg-status-busy text-xs font-medium text-white disabled:opacity-50"
              >
                🗑 Удалить сотрудников и следы
              </button>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-tg-bg/50 p-2">
      <div className="tabular-nums text-tg-text">{value}</div>
      <div className="text-tg-hint">{label}</div>
    </div>
  );
}
