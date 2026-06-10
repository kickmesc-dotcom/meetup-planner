/**
 * GHG8 P2.1.c: попап-история звания «🪱 Червь-пидор» по клику на бейдж 🪱
 * под аватаркой в ParticipantRow.
 *
 * Звание переходящее (одновременно ≤1 носитель), поэтому показываем общий
 * список назначений по убыванию `started_at`: первая строка с `ended_at=null`
 * — текущий носитель. Источник — `GET /api/worm/history`.
 */
import { useQuery } from "@tanstack/react-query";
import { fetchWormHistory } from "@/api/birthdays";
import { fetchUsers } from "@/api/availability";
import { useUI } from "@/store/ui";
import { humanizeApiError } from "@/api/client";
import { Spinner } from "@/components/Spinner";

export default function WormHistoryPopover() {
  const open = useUI((s) => s.showWormHistory);
  const setOpen = useUI((s) => s.setShowWormHistory);

  const historyQ = useQuery({
    queryKey: ["worm-history"],
    queryFn: () => fetchWormHistory(20),
    enabled: open,
    staleTime: 60_000,
  });
  // Имена берём из общего кэша участников (тот же queryKey, что и везде).
  const usersQ = useQuery({
    queryKey: ["users"],
    queryFn: fetchUsers,
    enabled: open,
    staleTime: 60_000,
  });

  if (!open) return null;

  const close = () => setOpen(false);

  const nameById = new Map(
    (usersQ.data ?? []).map((u) => [u.id, u.display_name]),
  );
  const fmt = (iso: string) =>
    new Date(iso).toLocaleDateString("ru-RU", {
      day: "2-digit",
      month: "long",
      year: "numeric",
    });
  const rows = historyQ.data ?? [];

  return (
    <div
      className="fixed inset-0 z-40 flex items-end justify-center bg-black/40"
      onClick={close}
    >
      <div
        className="w-full max-w-md rounded-t-2xl bg-tg-bg p-4 pb-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <div className="text-base font-semibold">🪱 Червь-пидор — история</div>
          <button
            type="button"
            onClick={close}
            className="text-tg-hint text-lg leading-none px-2"
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>

        {historyQ.isLoading && (
          <div className="flex items-center gap-2 text-sm text-tg-hint py-4">
            <Spinner size={14} />
            Загружаю историю…
          </div>
        )}

        {historyQ.isError && (
          <div className="text-sm text-red-500 py-2">
            {humanizeApiError(historyQ.error)}
          </div>
        )}

        {!historyQ.isLoading && !historyQ.isError && rows.length === 0 && (
          <div className="text-sm text-tg-hint py-2">
            Звание ещё никому не присваивалось.
          </div>
        )}

        {rows.length > 0 && (
          <div className="flex flex-col gap-2">
            {rows.map((r, i) => {
              const active = r.ended_at == null;
              const name = nameById.get(r.user_id) ?? `#${r.user_id}`;
              return (
                <div
                  key={`${r.user_id}-${r.started_at}-${i}`}
                  className={[
                    "rounded-lg p-3 text-sm",
                    active
                      ? "bg-tg-button/15 ring-1 ring-tg-button/40"
                      : "bg-tg-secondary-bg/60",
                  ].join(" ")}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{name}</span>
                    {active && (
                      <span className="text-xs text-tg-button">сейчас</span>
                    )}
                  </div>
                  <div className="mt-1 text-xs text-tg-hint">
                    {fmt(r.started_at)}
                    {r.ended_at ? ` — ${fmt(r.ended_at)}` : " — …"}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
