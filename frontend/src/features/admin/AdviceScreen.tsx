import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchAdvice,
  updateAdvicePhrases,
  updateAdviceEnabled,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import { Toggle } from "@/components/Checkbox";
import SubScreen from "./SubScreen";
import ReasonsEditor from "./ReasonsEditor";

interface Props {
  onBack: () => void;
}

const errAlert = (e: unknown) => {
  haptic("error");
  void showAlert(humanizeApiError(e));
};

/**
 * GHG8 T3.4: «магический шар». Бот выдаёт случайный совет на /advice,
 * #совет/#advice или упоминание «@bot …?». Здесь — тогл фичи + редактор пула
 * советов (тот же универсальный ReasonsEditor, что у причин лоха/чухана).
 * Счётчиков использования нет: рандом честный, без памяти (требование 13.06 #1).
 */
export default function AdviceScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const advice = useQuery({
    queryKey: ["admin", "advice"],
    queryFn: fetchAdvice,
    staleTime: 30_000,
  });

  const saveEnabled = useMutation({
    mutationFn: updateAdviceEnabled,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "advice"], data);
    },
    onError: errAlert,
  });

  const savePhrases = useMutation({
    mutationFn: updateAdvicePhrases,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "advice"], data);
    },
    onError: errAlert,
  });

  return (
    <SubScreen
      title="🔮 Магический шар"
      subtitle="/advice · #совет · @бот …?"
      onBack={onBack}
    >
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
        <div className="text-base font-semibold">⚙️ Совет дня</div>
        {advice.isPending || !advice.data ? (
          <ListSkeleton rows={1} />
        ) : (
          <Toggle
            checked={advice.data.enabled}
            onChange={(v) => saveEnabled.mutate(v)}
            label={
              advice.data.enabled
                ? "🔮 Бот раздаёт советы"
                : "💤 Советы выключены"
            }
          />
        )}
        <div className="text-xs text-tg-hint">
          Триггеры: команда <b>/advice</b>, хештег <b>#совет</b> / <b>#advice</b>{" "}
          в сообщении, либо упоминание <b>@бот</b> в тексте, который
          заканчивается на «?». Без «?» упоминание работает как раньше
          (рандом-фраза).
        </div>
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">💬 Варианты советов</div>
        <div className="text-xs text-tg-hint mb-2">
          Бот выбирает случайный вариант. Пустой список → дефолт из кода.
        </div>
        {advice.isPending || !advice.data ? (
          <ListSkeleton rows={5} />
        ) : (
          <ReasonsEditor
            initial={advice.data.phrases}
            isPending={savePhrases.isPending}
            placeholder="например: Звёзды говорят да, но звёзды — лохи"
            emptyHint="Пусто — будет использован дефолт из кода."
            onSave={(list) => savePhrases.mutate(list)}
          />
        )}
      </section>
    </SubScreen>
  );
}
