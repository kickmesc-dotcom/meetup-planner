/**
 * GHG7 P2.5: UI-тогглер `calendar.timeline_enabled`.
 *
 * Флаг живёт в `admin_config` (key `calendar.timeline_enabled`, default `false`).
 * До этой итерации включался только через `PUT /admin/calendar/timeline` курлом
 * с TWA-init-data — что вне Mini App неудобно. Теперь — Switch в админке.
 *
 * Запросы переиспользуют существующие `fetchCalendarTimelineFlag` /
 * `setCalendarTimelineFlag` из `@/api/admin`. Никаких новых эндпоинтов
 * не требуется — backend не меняется.
 *
 * При переключении инвалидируем тот же `queryKey`, что использует
 * `CalendarView.tsx` (`["admin", "calendar", "timeline"]`), чтобы новый/legacy
 * вид подхватился без релоада.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchCalendarTimelineFlag,
  setCalendarTimelineFlag,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

const TIMELINE_QUERY_KEY = ["admin", "calendar", "timeline"] as const;

export default function CalendarSettingsScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: TIMELINE_QUERY_KEY,
    queryFn: fetchCalendarTimelineFlag,
    staleTime: 30_000,
  });

  const mut = useMutation({
    mutationFn: (enabled: boolean) => setCalendarTimelineFlag(enabled),
    onSuccess: (out) => {
      haptic("success");
      // Тот же queryKey, что читает CalendarView — переключение применяется
      // без перезапуска Mini App, как только пользователь вернётся в календарь.
      qc.setQueryData(TIMELINE_QUERY_KEY, out);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const enabled = q.data?.enabled ?? false;
  const busy = q.isPending || mut.isPending;

  return (
    <SubScreen
      title="📅 Вид календаря"
      subtitle="Новый таймлайн / legacy-вид"
      onBack={onBack}
    >
      {q.isError && (
        <div className="rounded-lg bg-status-busy/10 p-2 text-xs text-status-busy">
          ⚠ {humanizeApiError(q.error)}
        </div>
      )}

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-base">🆕</span>
          <span className="text-sm font-semibold text-tg-text">
            Новый таймлайн-вид
          </span>
        </div>
        <div className="text-[11px] text-tg-hint">
          Горизонтальная лента с pinch-zoom и инерционной прокруткой. Активна
          при увеличениях <b>день / неделя / месяц</b>. Для остальных уровней
          (часы, 3/6 месяцев, год, все годы) используется legacy-вид независимо
          от этого тумблера.
        </div>
        <div className="flex items-center justify-between gap-2 pt-1">
          <div className="text-sm text-tg-text">
            Включён
            {q.isPending && (
              <span className="ml-2 text-[11px] text-tg-hint">загрузка…</span>
            )}
          </div>
          <Switch
            checked={enabled}
            disabled={busy}
            onChange={(v) => {
              haptic("selection");
              mut.mutate(v);
            }}
          />
        </div>
        <div className="text-[10px] text-tg-hint">
          Откат на legacy — переключить тумблер обратно. Никаких рестартов не
          требуется.
        </div>
      </section>
    </SubScreen>
  );
}

function Switch({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={[
        "shrink-0 inline-flex h-6 w-11 items-center rounded-full transition-colors disabled:opacity-50",
        checked ? "bg-tg-button" : "bg-tg-hint/30",
      ].join(" ")}
      role="switch"
      aria-checked={checked}
    >
      <span
        className={[
          "inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-5" : "translate-x-0.5",
        ].join(" ")}
      />
    </button>
  );
}
