import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchRPGenerator, updateRPGenerator, type RPGenerator } from "@/api/admin";
import { haptic } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

export default function RandomPhrasesGeneratorScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const gen = useQuery({ queryKey: ["admin", "rp-generator"], queryFn: fetchRPGenerator });

  const setGen = useMutation({
    mutationFn: updateRPGenerator,
    onSuccess: () => {
      haptic("light");
      qc.invalidateQueries({ queryKey: ["admin", "rp-generator"] });
    },
    onError: () => haptic("error"),
  });

  return (
    <SubScreen
      title="🧪 Генератор фраз"
      subtitle="Длина цитаты, история, шансы"
      onBack={onBack}
    >
      {gen.isPending || !gen.data ? (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
          <ListSkeleton rows={6} />
        </section>
      ) : (
        <GeneratorForm
          initial={gen.data}
          isPending={setGen.isPending}
          onSave={(body) => setGen.mutate(body)}
        />
      )}
      {setGen.isError && (
        <div className="rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
          ⚠ {String((setGen.error as Error)?.message ?? setGen.error)}
        </div>
      )}
    </SubScreen>
  );
}

function GeneratorForm({
  initial,
  isPending,
  onSave,
}: {
  initial: RPGenerator;
  isPending: boolean;
  onSave: (body: RPGenerator) => void;
}) {
  const [cmin, setCmin] = useState(String(initial.count_min));
  const [cmax, setCmax] = useState(String(initial.count_max));
  const [lookback, setLookback] = useState(String(initial.lookback_days));
  const [coll, setColl] = useState(Math.round(initial.collective_chance * 100));
  const [uchance, setUchance] = useState(Math.round(initial.user_chance * 100));

  useEffect(() => {
    setCmin(String(initial.count_min));
    setCmax(String(initial.count_max));
    setLookback(String(initial.lookback_days));
    setColl(Math.round(initial.collective_chance * 100));
    setUchance(Math.round(initial.user_chance * 100));
  }, [initial]);

  const cminN = clamp(parseInt(cmin, 10) || 2, 2, 6);
  const cmaxN = clamp(parseInt(cmax, 10) || 6, 2, 6);
  const lookbackN = clamp(parseInt(lookback, 10) || 7, 1, 365);

  const body: RPGenerator = {
    count_min: Math.min(cminN, cmaxN),
    count_max: Math.max(cminN, cmaxN),
    lookback_days: lookbackN,
    collective_chance: coll / 100,
    user_chance: uchance / 100,
  };

  const dirty =
    body.count_min !== initial.count_min ||
    body.count_max !== initial.count_max ||
    body.lookback_days !== initial.lookback_days ||
    Math.abs(body.collective_chance - initial.collective_chance) > 0.005 ||
    Math.abs(body.user_chance - initial.user_chance) > 0.005;

  return (
    <>
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
        <div>
          <div className="text-base font-semibold mb-1">📏 Длина цитаты</div>
          <div className="text-xs text-tg-hint mb-2">
            Сколько кусочков склеит бот. Бэкенд берёт random.randint(min, max).
          </div>
          <div className="grid grid-cols-2 gap-2">
            <NumField
              label="min (2..6)"
              value={cmin}
              onChange={setCmin}
              hint={`= ${cminN}`}
            />
            <NumField
              label="max (2..6)"
              value={cmax}
              onChange={setCmax}
              hint={`= ${cmaxN}`}
            />
          </div>
        </div>

        <div>
          <div className="text-base font-semibold mb-1">📚 Глубина истории</div>
          <div className="text-xs text-tg-hint mb-2">
            За сколько дней брать сообщения. Если за период пусто — fallback на
            последние 100.
          </div>
          <NumField
            label="дни (1..365)"
            value={lookback}
            onChange={setLookback}
            hint={`= ${lookbackN}`}
          />
        </div>

        <div>
          <div className="text-base font-semibold mb-1">🗣 Шанс «сводный хор»</div>
          <div className="text-xs text-tg-hint mb-2">
            Иначе — Шизо-цитата конкретного автора. Чем выше, тем чаще общий хор.
          </div>
          <PercentSlider value={coll} onChange={setColl} />
        </div>

        <div>
          <div className="text-base font-semibold mb-1">🎲 Шанс срабатывания</div>
          <div className="text-xs text-tg-hint mb-2">
            100% = job постит каждый раз. Понизь, чтобы было реже.
          </div>
          <PercentSlider value={uchance} onChange={setUchance} />
        </div>
      </section>

      <button
        type="button"
        disabled={!dirty || isPending}
        onClick={() => onSave(body)}
        className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform"
      >
        {isPending ? "Сохраняем…" : dirty ? "💾 Сохранить" : "✓ Сохранено"}
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

function PercentSlider({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex items-center gap-3 rounded-lg bg-tg-bg/40 px-2 py-2">
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value, 10))}
        className="flex-1 accent-tg-link"
      />
      <div className="w-12 text-right text-sm font-medium text-tg-text tabular-nums">
        {value}%
      </div>
    </div>
  );
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}
