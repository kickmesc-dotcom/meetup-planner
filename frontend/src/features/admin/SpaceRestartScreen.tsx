/**
 * GHG8 P14: рестарт HF Space — кнопка «сейчас» + расписание (once/interval).
 *
 * Backend: POST /admin/space/restart (202 уходит ДО рестарта),
 * GET/PUT /admin/space/restart-settings (`space_restart.schedule` в
 * admin_config). `available=false` = env HF_TOKEN не задан на Space —
 * всё дизейблим с подсказкой.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchSpaceRestartSettings,
  restartSpaceNow,
  updateSpaceRestartSettings,
  type SpaceRestartSchedule,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import { Spinner } from "@/components/Spinner";
import Icon, { InlineIcon } from "@/components/Icon";
import SubScreen from "./SubScreen";

import { useTx } from "@/i18n";
interface Props {
  onBack: () => void;
}

const QK = ["admin", "space-restart"] as const;

export default function SpaceRestartScreen({ onBack }: Props) {
  const { tx } = useTx();
  const qc = useQueryClient();

  const q = useQuery({ queryKey: QK, queryFn: fetchSpaceRestartSettings });

  const [draft, setDraft] = useState<SpaceRestartSchedule | null>(null);
  useEffect(() => {
    if (q.data && draft === null) setDraft(q.data.schedule);
  }, [q.data, draft]);

  const dirty = useMemo(() => {
    if (!q.data || !draft) return false;
    const s = q.data.schedule;
    return (
      draft.mode !== s.mode ||
      draft.at !== s.at ||
      draft.every_hours !== s.every_hours
    );
  }, [q.data, draft]);

  const restart = useMutation({
    mutationFn: restartSpaceNow,
    onSuccess: () => {
      haptic("success");
      void showAlert(
        tx("Space перезапускается. Mini App почти не заметит, но бот будет ") +
          tx("молчать ~5–7 минут, пока вебхук переустановится."),
      );
      void qc.invalidateQueries({ queryKey: QK });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const save = useMutation({
    mutationFn: updateSpaceRestartSettings,
    onSuccess: (out) => {
      haptic("success");
      setDraft(out.schedule);
      qc.setQueryData(QK, out);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const available = q.data?.available ?? false;

  return (
    <SubScreen
      title={tx("Рестарт Space")}
      subtitle={tx("Принудительный перезапуск backend-контейнера на HF")}
      onBack={onBack}
    >
      {q.isPending && <div className="text-xs text-tg-hint">{tx("Загрузка…")}</div>}
      {q.isError && (
        <div className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
          <InlineIcon name="alert" />
          {humanizeApiError(q.error)}
        </div>
      )}

      {q.data && !available && (
        <div className="rounded-tile bg-status-busy/10 p-2 text-xs text-status-busy">
          <InlineIcon name="alert" />
          Env <code>HF_TOKEN</code>{tx(
            "не задан в настройках Space — рестарт недоступен. Добавь write-токен HF в секреты Space.",
          )}</div>
      )}

      {q.data && (
        <section className="rounded-card bg-tg-secondary-bg/60 p-3 space-y-2">
          <div className="flex items-center gap-1.5 text-sm font-semibold text-tg-text">
            <Icon name="bolt" size={15} className="shrink-0" />{tx("Сейчас")}</div>
          <div className="text-xs text-tg-hint">{tx(
            "Лечит зависшие сетевые состояния (дохлый keep-alive-пул). Mini App переключается бесшовно; бот восстанавливает вебхук ~5–7 минут.",
          )}</div>
          <button
            type="button"
            disabled={!available || restart.isPending}
            onClick={async () => {
              haptic("medium");
              const ok = await showConfirm(
                tx("Перезапустить Space? Бот будет молчать ~5–7 минут."),
              );
              if (ok) restart.mutate();
            }}
            className="w-full min-h-11 rounded-tile bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform flex items-center justify-center gap-2"
          >
            {restart.isPending && <Spinner />}
            <Icon name="refresh" size={16} />{tx("Рестарт Space")}</button>
          {q.data.last_restart_at && (
            <div className="text-xs text-tg-hint">
              {tx("Последний рестарт: {when}", {
                when: fmtDt(q.data.last_restart_at),
              })}
            </div>
          )}
        </section>
      )}

      {draft && (
        <section className="rounded-card bg-tg-secondary-bg/60 p-3 space-y-3">
          <div>
            <div className="text-sm font-semibold text-tg-text">
              <span className="inline-flex items-center gap-1.5">
                <Icon name="calendar" size={15} />{tx("По расписанию")}</span>
            </div>
            <div className="text-xs text-tg-hint">{tx("Анти-луп: не чаще раза в 30 минут (после ручного — тоже).")}</div>
          </div>

          <div className="flex rounded-tile bg-tg-bg/60 p-0.5 text-xs">
            {(
              [
                ["off", tx("Выкл")],
                ["once", tx("Один раз")],
                ["interval", tx("Каждые N ч")],
              ] as const
            ).map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                onClick={() => {
                  haptic("selection");
                  setDraft({
                    mode,
                    at: mode === "once" ? draft.at : null,
                    every_hours:
                      mode === "interval" ? draft.every_hours ?? 24 : null,
                  });
                }}
                className={[
                  "flex-1 min-h-11 rounded-tile transition-colors",
                  draft.mode === mode
                    ? "bg-tg-button text-tg-button-text font-medium"
                    : "text-tg-hint",
                ].join(" ")}
              >
                {label}
              </button>
            ))}
          </div>

          {draft.mode === "once" && (
            <div>
              <div className="text-xs text-tg-hint mb-1">{tx("Дата и время (локальные)")}</div>
              <input
                type="datetime-local"
                value={isoToLocalInput(draft.at)}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    at: e.target.value
                      ? new Date(e.target.value).toISOString()
                      : null,
                  })
                }
                className="w-full rounded-tile bg-tg-bg/60 px-2 py-2 text-sm text-tg-text"
              />
            </div>
          )}

          {draft.mode === "interval" && (
            <div>
              <div className="text-xs text-tg-hint mb-1">
                {tx("Каждые {hours} ч", { hours: draft.every_hours ?? 24 })}
              </div>
              <input
                type="range"
                min={1}
                max={168}
                step={1}
                value={draft.every_hours ?? 24}
                onChange={(e) =>
                  setDraft({ ...draft, every_hours: Number(e.target.value) })
                }
                className="w-full accent-tg-button"
              />
              <div className="mt-1 text-2xs text-tg-hint">{tx("1 ч … 168 ч (неделя). Отсчёт — от последнего рестарта.")}</div>
            </div>
          )}

          {q.data?.next_restart_at && q.data.schedule.mode !== "off" && (
            <div className="rounded-tile bg-tg-bg/40 p-2 text-xs text-tg-text">
              {tx("Следующий рестарт: {when}", {
                when: fmtDt(q.data.next_restart_at),
              })}
            </div>
          )}

          <button
            type="button"
            disabled={!available || !dirty || save.isPending}
            onClick={() => {
              haptic("medium");
              save.mutate(draft);
            }}
            className="w-full min-h-11 rounded-tile bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform flex items-center justify-center gap-2"
          >
            {save.isPending && <Spinner />}
            <Icon name="save" size={16} />{tx("Сохранить расписание")}</button>
        </section>
      )}
    </SubScreen>
  );
}

function fmtDt(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** ISO (UTC) → значение для <input type="datetime-local"> в локальной TZ. */
function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
