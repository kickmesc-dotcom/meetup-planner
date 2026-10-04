/**
 * GHG11: «Режим бота» — мастер-свитчеры доставки.
 *
 * Каждая функция бота описывается одним из четырёх состояний:
 *   ВЫКЛ / Только в чате / Только в мини-аппе / Чат + мини-апп.
 *
 * Сверху — два МАСТЕР-свитчера: общий (все фичи, кроме ачивок) и отдельный для
 * ачивок. Перевод мастера переводит ВСЕ его фичи; точечная правка переводит
 * мастер в статус «Custom».
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  applyDeliveryAll,
  fetchDelivery,
  updateDelivery,
  type DeliveryFeature,
  type DeliveryMaster,
  type DeliveryMode,
} from "@/api/admin";
import { haptic } from "@/tg/webapp";
import SubScreen from "./SubScreen";

const MODE_ICON: Record<DeliveryMode, string> = {
  off: "⛔",
  chat: "💬",
  app: "📱",
  both: "🔀",
};

function MasterSwitcher({
  title,
  subtitle,
  value,
  labels,
  modes,
  busy,
  onChange,
}: {
  title: string;
  subtitle: string;
  value: DeliveryMaster;
  labels: Record<string, string>;
  modes: DeliveryMode[];
  busy: boolean;
  onChange: (mode: DeliveryMode) => void;
}) {
  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-tg-text">{title}</div>
          <div className="text-[11px] text-tg-hint">{subtitle}</div>
        </div>
        {value === "custom" && (
          <span className="shrink-0 rounded-full bg-status-busy/20 px-2 py-0.5 text-[11px] font-semibold text-status-busy">
            Custom
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        {modes.map((m) => {
          const active = value === m;
          return (
            <button
              key={m}
              type="button"
              disabled={busy}
              onClick={() => onChange(m)}
              className={[
                "min-h-11 rounded-lg px-2 py-1.5 text-xs font-medium active:scale-[0.98] disabled:opacity-60 transition-transform",
                active
                  ? "bg-tg-button text-tg-button-text"
                  : "bg-tg-bg/60 text-tg-text",
              ].join(" ")}
            >
              {MODE_ICON[m]} {labels[m] ?? m}
            </button>
          );
        })}
      </div>
    </section>
  );
}

function FeatureModeRow({
  feature,
  labels,
  modes,
  busy,
  onChange,
}: {
  feature: DeliveryFeature;
  labels: Record<string, string>;
  modes: DeliveryMode[];
  busy: boolean;
  onChange: (mode: DeliveryMode) => void;
}) {
  return (
    <div className="rounded-xl bg-tg-secondary-bg/60 p-2.5 space-y-1.5">
      <div className="min-w-0">
        <div className="text-sm font-semibold text-tg-text">{feature.label}</div>
        {feature.hint && (
          <div className="text-[11px] text-tg-hint">{feature.hint}</div>
        )}
      </div>
      <div className="grid grid-cols-4 gap-1">
        {modes.map((m) => {
          const active = feature.mode === m;
          return (
            <button
              key={m}
              type="button"
              disabled={busy}
              onClick={() => onChange(m)}
              title={labels[m] ?? m}
              className={[
                "min-h-9 rounded-lg px-1 py-1 text-[11px] font-medium active:scale-[0.98] disabled:opacity-60 transition-transform",
                active
                  ? "bg-tg-button text-tg-button-text"
                  : "bg-tg-bg/60 text-tg-text",
              ].join(" ")}
            >
              {MODE_ICON[m]} {m === "off" ? "выкл" : m === "chat" ? "чат" : m === "app" ? "апп" : "оба"}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function DeliveryScreen({ onBack }: { onBack: () => void }) {
  const qc = useQueryClient();
  const delivery = useQuery({
    queryKey: ["admin", "delivery"],
    queryFn: fetchDelivery,
  });

  const mut = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["admin"] });
    },
    onError: () => haptic("error"),
  });
  const busy = mut.isPending;
  const set = (fn: () => Promise<unknown>) => mut.mutate(fn);

  const data = delivery.data;
  const labels = data?.mode_labels ?? {
    off: "Выкл",
    chat: "Только в чате",
    app: "Только в мини-аппе",
    both: "Чат + мини-апп",
  };
  const modes: DeliveryMode[] = data?.modes ?? ["off", "chat", "app", "both"];

  const generalFeatures = (data?.features ?? []).filter(
    (f) => f.module === "general",
  );
  const achFeatures = (data?.features ?? []).filter(
    (f) => f.module === "achievements",
  );

  return (
    <SubScreen
      title="Режим бота"
      subtitle="Куда бот пишет: чат, мини-апп или оба"
      onBack={onBack}
    >
      <div className="rounded-xl bg-tg-secondary-bg/60 p-3 text-[11px] text-tg-hint">
        Одно состояние на функцию: <b>ВЫКЛ</b> — заглушка; <b>Только в чате</b> —
        активность в чате; <b>Только в мини-аппе</b> — всё видно в ленте аппа, в
        чат ничего; <b>Чат + мини-апп</b> — в чат и дублируется в ленте. Мастер
        переводит все свои функции разом; тронешь отдельную — мастер станет
        Custom.
      </div>

      {delivery.isPending && <div className="text-xs text-tg-hint">Загружаем…</div>}
      {delivery.isError && (
        <div className="rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
          ⚠ {String((delivery.error as Error)?.message ?? delivery.error)}
        </div>
      )}

      {data && (
        <>
          <MasterSwitcher
            title="🛠 Все функции (кроме ачивок)"
            subtitle="Принудительно переводит все механики бота"
            value={data.master_general}
            labels={labels}
            modes={modes}
            busy={busy}
            onChange={(m) =>
              set(() => updateDelivery({ master_general: m }))
            }
          />

          <MasterSwitcher
            title="🏆 Ачивки (отдельный модуль)"
            subtitle="Сбор, выдача и анонсы достижений — независимо от остального"
            value={data.master_achievements}
            labels={labels}
            modes={modes}
            busy={busy}
            onChange={(m) =>
              set(() => updateDelivery({ master_achievements: m }))
            }
          />

          {masterGlobalBar(modes, labels, busy, set)}

          {generalFeatures.length > 0 && (
            <details className="rounded-xl bg-tg-secondary-bg/30 p-2" open>
              <summary className="cursor-pointer px-1 text-xs font-semibold uppercase tracking-wide text-tg-hint">
                Механики по отдельности
              </summary>
              <div className="mt-2 space-y-2">
                {generalFeatures.map((f) => (
                  <FeatureModeRow
                    key={f.key}
                    feature={f}
                    labels={labels}
                    modes={modes}
                    busy={busy}
                    onChange={(m) =>
                      set(() => updateDelivery({ feature: f.key, mode: m }))
                    }
                  />
                ))}
              </div>
            </details>
          )}

          {achFeatures.length > 0 && (
            <details className="rounded-xl bg-tg-secondary-bg/30 p-2">
              <summary className="cursor-pointer px-1 text-xs font-semibold uppercase tracking-wide text-tg-hint">
                Ачивки
              </summary>
              <div className="mt-2 space-y-2">
                {achFeatures.map((f) => (
                  <FeatureModeRow
                    key={f.key}
                    feature={f}
                    labels={labels}
                    modes={modes}
                    busy={busy}
                    onChange={(m) =>
                      set(() => updateDelivery({ feature: f.key, mode: m }))
                    }
                  />
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </SubScreen>
  );
}

function masterGlobalBar(
  modes: DeliveryMode[],
  labels: Record<string, string>,
  busy: boolean,
  set: (fn: () => Promise<unknown>) => void,
) {
  return (
    <section className="rounded-xl border border-status-busy/30 p-2.5 space-y-1.5">
      <div className="text-[11px] text-tg-hint">
        Применить ко ВСЕМУ (оба мастера разом):
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        {modes.map((m) => (
          <button
            key={m}
            type="button"
            disabled={busy}
            onClick={() => {
              haptic("medium");
              set(() => applyDeliveryAll(m));
            }}
            className="min-h-10 rounded-lg bg-tg-bg/60 px-2 py-1.5 text-xs font-medium text-tg-text active:scale-[0.98] disabled:opacity-60 transition-transform"
          >
            {MODE_ICON[m]} {labels[m] ?? m}
          </button>
        ))}
      </div>
    </section>
  );
}
