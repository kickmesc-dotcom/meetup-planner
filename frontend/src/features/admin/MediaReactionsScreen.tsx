import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchMediaSettings,
  updateMediaSettings,
  fetchMediaSinglePhrases,
  updateMediaSinglePhrases,
  fetchMediaCollectionPhrases,
  updateMediaCollectionPhrases,
  fetchMediaEmojiWhitelist,
  updateMediaEmojiWhitelist,
  forceMediaReaction,
  type MediaReactionsSettings,
  type MediaMode,
  type MediaSingleResponseMode,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";
import ReasonsEditor from "./ReasonsEditor";

interface Props {
  onBack: () => void;
}

const errAlert = (e: unknown) => {
  haptic("error");
  void showAlert(humanizeApiError(e));
};

const MODE_LABELS: Record<MediaMode, string> = {
  always: "Всегда — реагировать сразу на каждый мем",
  chance: "С шансом — один ролл, реакция сразу при успехе",
  wait_then_chance: "Выждать → шанс — ролл, потом пауза (уступить людям)",
  never: "Никогда — подсистема молчит",
};

const SINGLE_RESPONSE_LABELS: Record<MediaSingleResponseMode, string> = {
  emoji: "Только эмодзи-реакция",
  phrase: "Только фраза (reply)",
  both: "И эмодзи, и фраза",
  random_one: "Случайно одно из двух",
};

/**
 * GHG7 P5.6.b: админ-UI медиа-реакций. Backend — services/media_reactions.py +
 * handlers/media_reactions.py. Структура экрана:
 *  1. Поведение (mode / шансы / что слать на одиночный мем / master-флаги) —
 *     авто-save при каждом изменении (как BotReactionsScreen).
 *  2. Пулы фраз single/collection + emoji whitelist — каждый ReasonsEditor со
 *     своим save-кнопкой (дефолты в коде, пусто → дефолт).
 *  3. Force-кнопки: отреагировать на последний мем/подборку (404 после рестарта
 *     Space — store в памяти процесса).
 */
export default function MediaReactionsScreen({ onBack }: Props) {
  const qc = useQueryClient();

  // --- поведение (авто-save) ---
  const settingsQ = useQuery({
    queryKey: ["admin", "media-reactions", "settings"],
    queryFn: fetchMediaSettings,
  });
  const [draft, setDraft] = useState<MediaReactionsSettings | null>(null);
  useEffect(() => {
    if (settingsQ.data) setDraft({ ...settingsQ.data });
  }, [settingsQ.data]);

  const saveSettings = useMutation({
    mutationFn: updateMediaSettings,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "media-reactions", "settings"], data);
    },
    onError: errAlert,
  });

  const patch = (p: Partial<MediaReactionsSettings>) => {
    if (!draft) return;
    const next = { ...draft, ...p };
    setDraft(next);
    saveSettings.mutate(next);
  };

  // --- пулы ---
  const singleQ = useQuery({
    queryKey: ["admin", "media-reactions", "single-phrases"],
    queryFn: fetchMediaSinglePhrases,
  });
  const collectionQ = useQuery({
    queryKey: ["admin", "media-reactions", "collection-phrases"],
    queryFn: fetchMediaCollectionPhrases,
  });
  const emojiQ = useQuery({
    queryKey: ["admin", "media-reactions", "emoji-whitelist"],
    queryFn: fetchMediaEmojiWhitelist,
  });

  const saveSingle = useMutation({
    mutationFn: updateMediaSinglePhrases,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "media-reactions", "single-phrases"], data);
    },
    onError: errAlert,
  });
  const saveCollection = useMutation({
    mutationFn: updateMediaCollectionPhrases,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "media-reactions", "collection-phrases"], data);
    },
    onError: errAlert,
  });
  const saveEmoji = useMutation({
    mutationFn: updateMediaEmojiWhitelist,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "media-reactions", "emoji-whitelist"], data);
    },
    onError: errAlert,
  });

  // --- force ---
  const force = useMutation({
    mutationFn: forceMediaReaction,
    onSuccess: (r) => {
      haptic("success");
      void showAlert(`Отреагировал на сообщение #${r.message_id}`);
    },
    onError: errAlert,
  });

  const usesChance = draft?.mode === "chance" || draft?.mode === "wait_then_chance";
  const usesWindow = draft?.mode === "wait_then_chance";

  return (
    <SubScreen
      title="🎭 Реакции на медиа"
      subtitle="Мемы и подборки участников"
      onBack={onBack}
    >
      {/* 1. Поведение */}
      {settingsQ.isPending || !draft ? (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
          <ListSkeleton rows={4} />
        </section>
      ) : (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
          <div className="text-xs text-tg-hint mb-1">
            Бот «оживляет» мемы участников, но не лезет поверх живого общения: в
            режиме «Выждать → шанс» сначала даёт людям время отреагировать.
          </div>

          <ToggleRow
            label="Подсистема включена"
            hint="Главный рубильник всех медиа-реакций."
            checked={draft.enabled}
            onChange={(v) => patch({ enabled: v })}
          />

          <div
            className={[
              "space-y-2 transition-opacity",
              draft.enabled ? "" : "opacity-40 pointer-events-none",
            ].join(" ")}
          >
            <div className="rounded-md bg-tg-bg/40 px-2 py-2">
              <div className="text-sm text-tg-text mb-1">Когда реагировать</div>
              <select
                value={draft.mode}
                onChange={(e) => {
                  haptic("selection");
                  patch({ mode: e.target.value as MediaMode });
                }}
                className="w-full rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
              >
                {(Object.keys(MODE_LABELS) as MediaMode[]).map((m) => (
                  <option key={m} value={m}>
                    {MODE_LABELS[m]}
                  </option>
                ))}
              </select>
            </div>

            {usesChance && (
              <div className="rounded-md bg-tg-bg/40 px-2 py-2 space-y-2">
                <PctRow
                  label="Шанс реакции"
                  hint="Вероятность, что бот вообще среагирует на мем (один ролл)."
                  value={draft.chance_pct}
                  onChange={(v) => patch({ chance_pct: v })}
                />
                {usesWindow && (
                  <NumRow
                    label="Грейс-окно, мин"
                    hint="Пауза после ролла — даём людям отреагировать самим (1–360)."
                    value={draft.wait_window_min}
                    min={1}
                    max={360}
                    onChange={(v) => patch({ wait_window_min: v })}
                  />
                )}
              </div>
            )}

            <div className="rounded-md bg-tg-bg/40 px-2 py-2">
              <div className="text-sm text-tg-text mb-1">
                Что слать на одиночный мем
              </div>
              <select
                value={draft.single_response_mode}
                onChange={(e) => {
                  haptic("selection");
                  patch({
                    single_response_mode: e.target
                      .value as MediaSingleResponseMode,
                  });
                }}
                className="w-full rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
              >
                {(
                  Object.keys(SINGLE_RESPONSE_LABELS) as MediaSingleResponseMode[]
                ).map((m) => (
                  <option key={m} value={m}>
                    {SINGLE_RESPONSE_LABELS[m]}
                  </option>
                ))}
              </select>
              <div className="text-[11px] text-tg-hint mt-1">
                Подборка (альбом 2+) всегда получает фразу-reply.
              </div>
            </div>

            <ToggleRow
              label="Реагировать на одиночные мемы"
              checked={draft.single_enabled}
              onChange={(v) => patch({ single_enabled: v })}
            />
            <ToggleRow
              label="Реагировать на подборки (альбомы)"
              checked={draft.collection_enabled}
              onChange={(v) => patch({ collection_enabled: v })}
            />
          </div>
        </section>
      )}

      {/* 2. Пулы фраз */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 mt-3 space-y-2">
        <div className="text-sm font-semibold text-tg-text">
          😎 Фразы на одиночный мем
        </div>
        <div className="text-[11px] text-tg-hint">
          <code>%username%</code> заменяется на имя автора.
        </div>
        {singleQ.isPending || !singleQ.data ? (
          <ListSkeleton rows={3} />
        ) : (
          <ReasonsEditor
            initial={singleQ.data.phrases}
            isPending={saveSingle.isPending}
            placeholder="новая фраза…"
            onSave={(list) => saveSingle.mutate(list)}
          />
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 mt-3 space-y-2">
        <div className="text-sm font-semibold text-tg-text">
          🎞 Фразы на подборку
        </div>
        <div className="text-[11px] text-tg-hint">
          Reply на альбом из 2+ медиа. <code>%username%</code> — имя автора.
        </div>
        {collectionQ.isPending || !collectionQ.data ? (
          <ListSkeleton rows={3} />
        ) : (
          <ReasonsEditor
            initial={collectionQ.data.phrases}
            isPending={saveCollection.isPending}
            placeholder="новая фраза…"
            onSave={(list) => saveCollection.mutate(list)}
          />
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 mt-3 space-y-2">
        <div className="text-sm font-semibold text-tg-text">
          🔥 Эмодзи-реакции
        </div>
        <div className="text-[11px] text-tg-hint">
          Только из поддерживаемого Telegram набора. Неподдерживаемый эмодзи бот
          молча пропустит.
        </div>
        {emojiQ.isPending || !emojiQ.data ? (
          <ListSkeleton rows={2} />
        ) : (
          <ReasonsEditor
            initial={emojiQ.data.phrases}
            isPending={saveEmoji.isPending}
            placeholder="новый эмодзи…"
            onSave={(list) => saveEmoji.mutate(list)}
          />
        )}
      </section>

      {/* 3. Force-кнопки */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 mt-3 space-y-2">
        <div className="text-sm font-semibold text-tg-text">
          ⚡ Принудительная реакция
        </div>
        <div className="text-[11px] text-tg-hint mb-1">
          Отреагировать на последнее медиа в группе сейчас (без серии/шанса).
          После рестарта бота «последнее медиа» забывается.
        </div>
        <div className="flex gap-2">
          <ForceButton
            label="😎 На последний мем"
            disabled={force.isPending}
            onClick={() => {
              haptic("medium");
              force.mutate("single");
            }}
          />
          <ForceButton
            label="🎞 На последнюю подборку"
            disabled={force.isPending}
            onClick={() => {
              haptic("medium");
              force.mutate("collection");
            }}
          />
        </div>
      </section>
    </SubScreen>
  );
}

function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-2 rounded-md bg-tg-bg/40 px-2 py-2">
      <div className="min-w-0">
        <div className="text-sm text-tg-text">{label}</div>
        {hint && <div className="text-[11px] text-tg-hint">{hint}</div>}
      </div>
      <Switch
        checked={checked}
        onChange={(v) => {
          haptic("selection");
          onChange(v);
        }}
      />
    </div>
  );
}

function PctRow({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="min-w-0">
        <div className="text-sm text-tg-text">{label}</div>
        {hint && <div className="text-[11px] text-tg-hint">{hint}</div>}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <input
          type="number"
          min={0}
          max={100}
          value={value}
          onChange={(e) => {
            const n = Math.max(0, Math.min(100, Number(e.target.value) || 0));
            onChange(n);
          }}
          className="w-16 rounded-md bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text text-right outline-none border border-transparent focus:border-tg-link tabular-nums"
        />
        <span className="text-xs text-tg-hint">%</span>
      </div>
    </div>
  );
}

function NumRow({
  label,
  hint,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="min-w-0">
        <div className="text-sm text-tg-text">{label}</div>
        {hint && <div className="text-[11px] text-tg-hint">{hint}</div>}
      </div>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => {
          const n = Math.max(min, Math.min(max, Number(e.target.value) || min));
          onChange(n);
        }}
        className="w-16 shrink-0 rounded-md bg-tg-bg/70 px-2 py-1.5 text-sm text-tg-text text-right outline-none border border-transparent focus:border-tg-link tabular-nums"
      />
    </div>
  );
}

function ForceButton({
  label,
  disabled,
  onClick,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="flex-1 min-h-11 rounded-lg bg-tg-bg/70 px-2 py-2 text-xs text-tg-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-1.5"
    >
      {disabled && <Spinner />}
      {label}
    </button>
  );
}

function Switch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={[
        "shrink-0 inline-flex h-6 w-11 items-center rounded-full transition-colors",
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
