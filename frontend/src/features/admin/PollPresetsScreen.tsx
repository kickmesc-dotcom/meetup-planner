import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchPollPresetsAdmin,
  updatePollPresets,
  type PollPreset,
} from "@/api/admin";
import { haptic, showAlert } from "@/tg/webapp";
import { humanizeApiError } from "@/api/client";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

const DEFAULTS: PollPreset[] = [
  { start: "12:00", end: "15:00" },
  { start: "15:00", end: "18:00" },
  { start: "18:00", end: "20:00" },
  { start: "20:00", end: "23:00" },
];

function isValid(p: PollPreset): boolean {
  const re = /^([01]\d|2[0-3]):[0-5]\d$/;
  if (!re.test(p.start) || !re.test(p.end)) return false;
  return p.start < p.end;
}

export default function PollPresetsScreen({ onBack }: Props) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "poll-presets"],
    queryFn: fetchPollPresetsAdmin,
  });

  const [draft, setDraft] = useState<PollPreset[]>([]);
  useEffect(() => {
    if (q.data?.presets) setDraft(q.data.presets);
  }, [q.data]);

  const save = useMutation({
    mutationFn: updatePollPresets,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "poll-presets"] });
      qc.invalidateQueries({ queryKey: ["poll-presets"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const allValid = draft.length > 0 && draft.every(isValid);

  return (
    <SubScreen
      title="🕒 Пресеты времени"
      subtitle="Что показывать при создании опроса / авто-подборе"
      onBack={onBack}
    >
      {q.isPending || !q.data ? (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
          <ListSkeleton rows={4} />
        </section>
      ) : (
        <>
          <div className="space-y-2">
            {draft.map((p, i) => (
              <PresetRow
                key={i}
                preset={p}
                onChange={(np) =>
                  setDraft((d) => d.map((x, idx) => (idx === i ? np : x)))
                }
                onRemove={() =>
                  setDraft((d) => d.filter((_, idx) => idx !== i))
                }
              />
            ))}
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                haptic("selection");
                setDraft((d) => [...d, { start: "20:00", end: "23:00" }]);
              }}
              className="rounded-lg bg-tg-secondary-bg/70 px-3 py-2 text-sm text-tg-text"
            >
              ➕ слот
            </button>
            <button
              type="button"
              onClick={() => {
                haptic("warning");
                setDraft(DEFAULTS.map((p) => ({ ...p })));
              }}
              className="rounded-lg bg-tg-secondary-bg/70 px-3 py-2 text-sm text-tg-text"
            >
              ↻ дефолт
            </button>
          </div>

          <button
            type="button"
            disabled={!allValid || save.isPending}
            onClick={() => {
              haptic("medium");
              save.mutate(draft);
            }}
            className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
          >
            {save.isPending && <Spinner />}
            {save.isPending ? "Сохраняем…" : allValid ? "💾 Сохранить" : "⚠ Проверь HH:MM"}
          </button>
          {save.isError && (
            <div className="rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
              ⚠ {humanizeApiError(save.error)}
            </div>
          )}
        </>
      )}
    </SubScreen>
  );
}

function PresetRow({
  preset,
  onChange,
  onRemove,
}: {
  preset: PollPreset;
  onChange: (p: PollPreset) => void;
  onRemove: () => void;
}) {
  const valid = isValid(preset);
  return (
    <section
      className={`rounded-xl p-3 ${valid ? "bg-tg-secondary-bg/60" : "bg-status-busy/10 ring-1 ring-status-busy/40"}`}
    >
      <div className="grid grid-cols-[1fr_auto_1fr_auto] gap-2 items-center">
        <input
          type="time"
          value={preset.start}
          onChange={(e) => onChange({ ...preset, start: e.target.value })}
          className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text border-2 border-tg-secondary-bg/80 focus:border-tg-link outline-none"
        />
        <span className="text-tg-hint">→</span>
        <input
          type="time"
          value={preset.end}
          onChange={(e) => onChange({ ...preset, end: e.target.value })}
          className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text border-2 border-tg-secondary-bg/80 focus:border-tg-link outline-none"
        />
        <button
          type="button"
          onClick={() => {
            haptic("warning");
            onRemove();
          }}
          className="rounded-lg bg-status-busy/20 px-2 py-2 text-status-busy"
          aria-label="Удалить"
        >
          ✕
        </button>
      </div>
    </section>
  );
}
