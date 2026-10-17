/**
 * GHG7 P0.2.e: попап-поповер по клику на корону 👑 на календаре.
 *
 * Показывает: имя загадавшего ролл (если это была ручная крутилка),
 * причину (`reason_text`), время ролла, признак «червь-пидор» (особая
 * стилизация). Источники данных — `GET /api/calendar/loser/{date}/{user_id}`.
 *
 * Поведение по источникам (GHG7 P9.4.c — ИСПРАВЛЕНА прежняя инверсия):
 *  - `source='auto'`   — 👑 «Лох дня» (автолох-по-расписанию). Системный
 *    rolled_by не важен, показываем только причину.
 *  - `source='manual'` — 👑 «Лох дня» (тихий admin force-reroll). Официальный
 *    лох, идёт в статистику.
 *  - `source='duel'`   — 🤡 «Автолох» (ручная дуэль /loser + LoserSheet).
 *    Обязательно показываем, кто дёрнул (`rolled_by_name`); в статистику НЕ идёт.
 *  - `was_worm=true`   — «🪱 Особая номинация: Червь-пидор» поверх всего;
 *    причина = `WORM_REASON_TEXT`, фоном остаётся источник.
 */
import { useQuery } from "@tanstack/react-query";
import { fetchLoserReason } from "@/api/birthdays";
import { useUI } from "@/store/ui";
import { humanizeApiError } from "@/api/client";
import { Spinner } from "@/components/Spinner";

export default function LoserReasonPopover() {
  const popover = useUI((s) => s.loserReasonPopover);
  const setPopover = useUI((s) => s.setLoserReasonPopover);

  const enabled = popover != null;
  const query = useQuery({
    queryKey: ["loser-reason", popover?.userId, popover?.date],
    queryFn: () => {
      if (!popover) throw new Error("no_popover");
      return fetchLoserReason(popover.date, popover.userId);
    },
    enabled,
    staleTime: 60_000,
  });

  if (!popover) return null;

  const close = () => setPopover(null);

  const reason = query.data;
  // GHG7 P9.4.c: duel → 🤡 «Автолох», всё остальное (auto/manual/null) → 👑.
  const isDuel = reason?.source === "duel";
  const sourceLabel = isDuel ? "🤡 Автолох" : "👑 Лох дня";

  const rolledAtFormatted = reason
    ? new Date(reason.rolled_at).toLocaleString("ru-RU", {
        day: "2-digit",
        month: "long",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

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
          <div className="text-base font-semibold">
            {reason?.was_worm
              ? `🪱 Червь-пидор — ${popover.displayName}`
              : `${isDuel ? "🤡" : "👑"} ${popover.displayName}`}
          </div>
          <button
            type="button"
            onClick={close}
            className="text-tg-hint text-lg leading-none px-2"
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>

        {query.isLoading && (
          <div className="flex items-center gap-2 text-sm text-tg-hint py-4">
            <Spinner size={14} />
            Загружаю причину…
          </div>
        )}

        {query.isError && (
          <div className="text-sm text-red-500 py-2">
            {humanizeApiError(query.error)}
          </div>
        )}

        {reason && (
          <div className="flex flex-col gap-2">
            <div className="rounded-lg bg-tg-secondary-bg/60 p-3 text-sm">
              <div className="text-xs text-tg-hint mb-1">
                {sourceLabel} · {rolledAtFormatted}
              </div>
              {reason.was_worm ? (
                <div className="font-medium">
                  Эта корона — за «Червь-пидор». Редчайшее переходящее
                  звание. Носи с честью (или с позором).
                </div>
              ) : (
                <div>
                  <span className="text-tg-hint">Причина: </span>
                  {reason.reason_text || "—"}
                </div>
              )}
              {isDuel && reason.rolled_by_name && (
                <div className="mt-2 text-xs text-tg-hint">
                  Покрутил рулетку: {reason.rolled_by_name}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
