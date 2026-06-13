import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  adminLoserRollNow,
  clearLoserReasonUseCounts,
  setLoserReasonUseCount,
  fetchAutoLoser,
  fetchLoserHistory,
  fetchLoserReasons,
  fetchLoserReasonUseCounts,
  updateAutoLoser,
  updateLoserReasons,
  type AutoLoserSettings,
} from "@/api/admin";
import type { User } from "@/types";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import { Toggle } from "@/components/Checkbox";
import { Spinner } from "@/components/Spinner";
import SubScreen from "../SubScreen";
import ReasonsEditor from "../ReasonsEditor";

interface Props {
  users: User[];
  onBack: () => void;
}

// GHG7 P2.3.h: единый экран «Лох дня». Раньше настройки автовыбора жили в
// отдельном AutoLoserScreen («Запланированные публикации»), а ручной реролл /
// история / шаблоны — здесь. Два пункта меню назывались одинаково «Лох дня» и
// путали. Бэкенд хранит всё под одними ключами autoloser.* (источник правды
// один — get_autoloser_settings), так что слияние чисто UI, без риска для
// данных. Порядок секций повторяет ChukhanScreen: настройки → реролл →
// шаблоны → история.
export default function LoserScreen({ users, onBack }: Props) {
  const qc = useQueryClient();

  const auto = useQuery({ queryKey: ["admin", "autoloser"], queryFn: fetchAutoLoser });
  const reasons = useQuery({
    queryKey: ["admin", "loser-reasons"],
    queryFn: fetchLoserReasons,
  });
  const useCounts = useQuery({
    queryKey: ["admin", "loser-reasons-use-counts"],
    queryFn: fetchLoserReasonUseCounts,
  });
  const history = useQuery({
    queryKey: ["admin", "loser-history"],
    queryFn: fetchLoserHistory,
  });

  const saveAuto = useMutation({
    mutationFn: updateAutoLoser,
    // U3: оптимистический update — сразу пишем в кэш, на error откатываем.
    onMutate: async (next) => {
      await qc.cancelQueries({ queryKey: ["admin", "autoloser"] });
      const prev = qc.getQueryData<AutoLoserSettings>(["admin", "autoloser"]);
      qc.setQueryData<AutoLoserSettings>(["admin", "autoloser"], next);
      return { prev };
    },
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "autoloser"] });
      qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
    },
    onError: (e, _vars, ctx) => {
      haptic("error");
      if (ctx?.prev) qc.setQueryData(["admin", "autoloser"], ctx.prev);
      void showAlert(humanizeApiError(e));
    },
  });

  const rollNow = useMutation({
    mutationFn: adminLoserRollNow,
    onSuccess: (res) => {
      haptic(res.ok ? "success" : "warning");
      qc.invalidateQueries({ queryKey: ["admin", "loser-history"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const saveReasons = useMutation({
    mutationFn: updateLoserReasons,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "loser-reasons"] });
      qc.invalidateQueries({ queryKey: ["admin", "loser-reasons-use-counts"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });
  const resetCounts = useMutation({
    mutationFn: clearLoserReasonUseCounts,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "loser-reasons-use-counts"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });
  const setCount = useMutation({
    mutationFn: ({ phrase, count }: { phrase: string; count: number }) =>
      setLoserReasonUseCount(phrase, count),
    onSuccess: (res) => {
      haptic("success");
      qc.setQueryData(["admin", "loser-reasons-use-counts"], res);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const userById = Object.fromEntries(users.map((u) => [u.id, u] as const));

  return (
    <SubScreen
      title="👑 Лох дня"
      subtitle="Автовыбор, ручной реролл, шаблоны, история"
      onBack={onBack}
    >
      {/* Настройки автовыбора (бывший AutoLoserScreen). */}
      {auto.isPending || !auto.data ? (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
          <ListSkeleton rows={4} />
        </section>
      ) : (
        <AutoLoserForm
          initial={auto.data}
          isPending={saveAuto.isPending}
          onSave={(body) => saveAuto.mutate(body)}
        />
      )}
      {saveAuto.isError && (
        <div className="rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
          ⚠ {String((saveAuto.error as Error)?.message ?? saveAuto.error)}
        </div>
      )}

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">🎲 Принудительный re-roll</div>
        <div className="text-xs text-tg-hint mb-2">
          Прокручивает выбор лоха прямо сейчас и публикует результат в общий чат.
        </div>
        <button
          type="button"
          disabled={rollNow.isPending}
          onClick={() => {
            haptic("medium");
            if (confirm("Крутануть лоха сейчас?")) rollNow.mutate();
          }}
          className="w-full min-h-11 rounded-lg bg-tg-button py-2.5 text-sm font-medium text-tg-button-text disabled:opacity-50 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
        >
          {rollNow.isPending && <Spinner />}
          {rollNow.isPending ? "Катаем…" : "🎲 Крутануть лоха"}
        </button>
        {rollNow.isError && (
          <div className="mt-2 rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {String((rollNow.error as Error)?.message ?? rollNow.error)}
          </div>
        )}
        {rollNow.isSuccess && !rollNow.isPending && (
          <div
            className={`mt-2 rounded-md p-2 text-xs ${
              rollNow.data.ok
                ? "bg-status-free/10 text-status-free"
                : "bg-status-busy/10 text-status-busy"
            }`}
          >
            {rollNow.data.ok
              ? "✓ Готово — лох уже в чате."
              : `⚠ ${rollNow.data.error ?? "Не удалось крутануть"}`}
          </div>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">🤡 Шаблоны фраз</div>
        <div className="text-xs text-tg-hint mb-2">
          Бот выбирает случайную фразу при roll'е лоха. Пустой список → дефолт из кода.
        </div>
        {reasons.isPending || !reasons.data ? (
          <ListSkeleton rows={5} />
        ) : (
          <ReasonsEditor
            initial={reasons.data.reasons}
            isPending={saveReasons.isPending}
            placeholder="например: снова забыл выпить таблетки"
            onSave={(list) => saveReasons.mutate(list)}
            useCounts={useCounts.data?.counts}
            onResetCounts={() => resetCounts.mutate()}
            resetCountsPending={resetCounts.isPending}
            onSetCount={(phrase, count) => setCount.mutate({ phrase, count })}
          />
        )}
        {saveReasons.isError && (
          <div className="mt-2 rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {String((saveReasons.error as Error)?.message ?? saveReasons.error)}
          </div>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">📜 История лохов</div>
        <div className="text-xs text-tg-hint mb-2">Последние roll'ы.</div>
        {history.isPending ? (
          <ListSkeleton rows={5} />
        ) : (history.data ?? []).length === 0 ? (
          <div className="text-xs text-tg-hint">Пока пусто.</div>
        ) : (
          <div className="divide-y divide-tg-bg/40">
            {(history.data ?? []).map((h) => {
              const u = userById[h.loser_user_id];
              const color = u?.color_hex ?? "#888";
              return (
                <div key={h.id} className="flex items-start gap-2 py-1.5">
                  <div
                    className="w-7 h-7 rounded-full inline-flex items-center justify-center text-white text-xs font-medium shrink-0 mt-0.5"
                    style={{ background: color }}
                  >
                    {(u?.display_name ?? "?")[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-tg-text">{u?.display_name ?? `#${h.loser_user_id}`}</div>
                    {h.reason_text && (
                      <div className="text-[11px] text-tg-hint italic">{h.reason_text}</div>
                    )}
                  </div>
                  <div className="text-[10px] text-tg-hint tabular-nums whitespace-nowrap mt-1">
                    {format(new Date(h.rolled_at), "dd.MM HH:mm")}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </SubScreen>
  );
}

// Бывший AutoLoserScreen.tsx — настройки автовыбора лоха дня. P2.3.c: подсказки
// переписаны короче и понятнее (раньше путали окно и частоту).
function AutoLoserForm({
  initial,
  isPending,
  onSave,
}: {
  initial: AutoLoserSettings;
  isPending: boolean;
  onSave: (body: AutoLoserSettings) => void;
}) {
  const [enabled, setEnabled] = useState(initial.enabled);
  const [startH, setStartH] = useState(String(initial.window_start_hour));
  const [endH, setEndH] = useState(String(initial.window_end_hour));
  const [interval, setInterval_] = useState(String(initial.interval_hours));

  useEffect(() => {
    setEnabled(initial.enabled);
    setStartH(String(initial.window_start_hour));
    setEndH(String(initial.window_end_hour));
    setInterval_(String(initial.interval_hours));
  }, [initial]);

  const startN = clamp(parseInt(startH, 10) || 0, 0, 23);
  const endN = clamp(parseInt(endH, 10) || 22, 0, 23);
  const intervalN = clamp(parseInt(interval, 10) || 0, 0, 72);

  const body: AutoLoserSettings = {
    enabled,
    window_start_hour: startN,
    window_end_hour: endN,
    interval_hours: intervalN,
  };

  const dirty =
    body.enabled !== initial.enabled ||
    body.window_start_hour !== initial.window_start_hour ||
    body.window_end_hour !== initial.window_end_hour ||
    body.interval_hours !== initial.interval_hours;

  return (
    <>
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
        <div className="text-base font-semibold">⚙️ Автовыбор</div>
        <Toggle
          checked={enabled}
          onChange={setEnabled}
          label={enabled ? "🤖 Бот сам выбирает лоха" : "💤 Автовыбор выключен"}
        />

        <div>
          <div className="text-base font-semibold mb-1">🕐 В какие часы</div>
          <div className="text-xs text-tg-hint mb-2">
            Часы суток (время сервера, 0–23), когда бот может назначить лоха.
            Вне окна — молчит.
          </div>
          <div className="grid grid-cols-2 gap-2">
            <NumField label="с (0..23)" value={startH} onChange={setStartH} hint={`= ${startN}:00`} />
            <NumField label="до (0..23)" value={endH} onChange={setEndH} hint={`= ${endN}:00`} />
          </div>
        </div>

        <div>
          <div className="text-base font-semibold mb-1">⏳ Как часто</div>
          <div className="text-xs text-tg-hint mb-2">
            <b>0</b> — один раз в сутки в случайный момент окна. <b>N ≥ 1</b> —
            каждые N часов внутри окна (например, 6 → 4 раза за окно 10–22).
          </div>
          <NumField
            label="часов (0..72)"
            value={interval}
            onChange={setInterval_}
            hint={intervalN === 0 ? "= раз в день, случайно" : `= каждые ${intervalN} ч`}
          />
        </div>
      </section>

      <button
        type="button"
        disabled={!dirty || isPending}
        onClick={() => onSave(body)}
        className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
      >
        {isPending && <Spinner />}
        {isPending ? "Сохраняем…" : dirty ? "💾 Сохранить настройки автовыбора" : "✓ Сохранено"}
      </button>
    </>
  );
}

function NumField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] text-tg-hint">{label}</span>
      <input
        type="text"
        inputMode="numeric"
        value={value}
        onChange={(e) => onChange(e.target.value.replace(/[^0-9]/g, ""))}
        className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text text-center tabular-nums outline-none border border-transparent focus:border-tg-link"
      />
      {hint && <span className="text-[10px] text-tg-hint">{hint}</span>}
    </label>
  );
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}
