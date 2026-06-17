import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchPostingAlerts,
  retryChukhanPosting,
  type PostingAlerts,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import { Spinner } from "@/components/Spinner";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

function fmtDt(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/**
 * GHG8 T3.3 (п.18): блок алёртов «лох/чухан не запостился в чат».
 *
 * ⚠️ Заморозка: данные read-only (бэк только SELECT по outbox/weekly_chukhan,
 * outbox лоха НЕ трогаем — он работает идеально). Перепрогон есть ТОЛЬКО для
 * чухана (зовёт существующую retry_undelivered_chukhan, штатный путь). У лоха
 * кнопки нет — его outbox-ретрай добивает доставку сам; здесь лишь показываем
 * терминально-застрявшие (expired) для информации.
 */
export default function PostingAlertsScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const alerts = useQuery({
    queryKey: ["admin", "posting-alerts"],
    queryFn: fetchPostingAlerts,
    staleTime: 10_000,
  });

  const retryChukhan = useMutation({
    mutationFn: retryChukhanPosting,
    onSuccess: (res) => {
      haptic(res.delivered ? "success" : "warning");
      qc.invalidateQueries({ queryKey: ["admin", "posting-alerts"] });
      void showAlert(
        res.delivered
          ? "✅ Чухан дослан в чат."
          : "⚠️ Не удалось дослать (канал недоступен?). Штатный ретрай попробует снова сам.",
      );
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const data: PostingAlerts | undefined = alerts.data;
  const hasChukhan = !!data?.chukhan;
  const loserList = data?.loser ?? [];

  return (
    <SubScreen
      title="🚨 Алёрты постинга"
      subtitle="Лох / чухан не вышли в чат"
      onBack={onBack}
    >
      {alerts.isPending ? (
        <ListSkeleton rows={3} />
      ) : alerts.isError ? (
        <div className="rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
          ⚠ {humanizeApiError(alerts.error)}
        </div>
      ) : data && data.total === 0 ? (
        <section className="rounded-xl bg-status-free/10 p-4 text-center">
          <div className="text-2xl mb-1">✓</div>
          <div className="text-sm text-status-free font-medium">Всё доставлено</div>
          <div className="text-xs text-tg-hint mt-1">
            Пропущенных постов нет. Лох и чухан вышли в чат как надо.
          </div>
        </section>
      ) : (
        <>
          {/* Чухан: алёрт + кнопка дослать */}
          {hasChukhan && (
            <section className="rounded-xl bg-status-busy/15 border border-status-busy/40 p-3 space-y-2">
              <div className="text-sm font-semibold text-status-busy">
                💩 Чухан недели не запостился
              </div>
              <div className="text-xs text-tg-text">
                Назначен <b>{data!.chukhan!.user_name ?? "—"}</b> на неделю с{" "}
                {fmtDt(data!.chukhan!.week_start)}, но пост в чат не вышел
                (создан {fmtDt(data!.chukhan!.created_at)}).
              </div>
              <button
                type="button"
                disabled={retryChukhan.isPending}
                onClick={async () => {
                  haptic("medium");
                  const ok = await showConfirm(
                    "Дослать чухана в чат сейчас? (тот же пост, без пометки «вручную»)",
                  );
                  if (ok) retryChukhan.mutate();
                }}
                className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-50 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
              >
                {retryChukhan.isPending && <Spinner />}
                {retryChukhan.isPending ? "Досылаем…" : "📤 Дослать чухана сейчас"}
              </button>
            </section>
          )}

          {/* Лох: только информационный список expired (без кнопки) */}
          {loserList.length > 0 && (
            <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
              <div className="text-sm font-semibold">
                🤡 Автолох не доставлен ({loserList.length})
              </div>
              <div className="text-xs text-tg-hint">
                Эти роллы исчерпали все попытки доставки (≈час ретраев). Перепрогон
                лоха не делаем — механизм доставки трогать нельзя; показано для
                информации.
              </div>
              <div className="rounded-lg bg-tg-bg/40 divide-y divide-tg-secondary-bg/40">
                {loserList.map((l) => (
                  <div key={l.outbox_id} className="px-2 py-2 space-y-0.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm text-tg-text truncate">
                        {l.loser_name ?? "—"}
                      </span>
                      <span className="text-[10px] text-tg-hint tabular-nums shrink-0">
                        {fmtDt(l.rolled_at)}
                      </span>
                    </div>
                    {l.reason_text && (
                      <div className="text-[11px] text-tg-hint truncate">
                        {l.reason_text}
                      </div>
                    )}
                    {l.last_error && (
                      <div className="text-[10px] text-status-busy truncate">
                        ⚠ {l.last_error}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </SubScreen>
  );
}
