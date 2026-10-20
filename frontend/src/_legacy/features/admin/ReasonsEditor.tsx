import { useEffect, useMemo, useState } from "react";
import type { PhraseMetaItem, PhraseSource } from "@/api/admin";
import { Spinner } from "@/components/Spinner";
import { haptic } from "@/tg/webapp";

/**
 * GHG6 AD2/AD3: универсальный редактор списка фраз — используется и для
 * loser_reasons, и для chukhan_reasons. Поведение идентично, разнятся только
 * данные/API.
 *
 * GHG8 J.2: ревамп под телефон —
 * - фразы показываются ПОЛНОСТЬЮ (перенос строк, без обрезки);
 * - инлайн-правка существующей фразы (не только удалить/добавить);
 * - бейдж источника (🤖 ИИ / ✍️ моя / ⬇️ импорт / 🎭 тип) — если передан `meta`;
 * - мягкое скрытие (👁/🚫) — фраза остаётся в пуле, но выпадает из ротации;
 * - фильтры «все / ИИ / мои / скрытые» + массовые действия.
 *
 * Вся мета-часть опциональна: без `meta` компонент работает как раньше.
 */
export interface ReasonsEditorProps {
  initial: string[];
  isPending: boolean;
  placeholder?: string;
  emptyHint?: string;
  onSave: (list: string[]) => void;
  useCounts?: Record<string, number>;
  onResetCounts?: () => void;
  resetCountsPending?: boolean;
  /** Точечный сброс счётчика одной фразы (use:N → 0). */
  onSetCount?: (phrase: string, count: number) => void;
  /** J.2: метаданные фраз (по тексту фразы). */
  meta?: Record<string, PhraseMetaItem>;
  /** J.2: смена источника/скрытия одной фразы. */
  onSetMeta?: (phrase: string, patch: { source?: PhraseSource; hidden?: boolean }) => void;
  /** J.2: массовые действия по фразам. */
  onBulkMeta?: (phrases: string[], patch: { source?: PhraseSource; hidden?: boolean }) => void;
}

type Filter = "all" | "ai" | "mine" | "hidden";

const sourceIcon = (s: PhraseSource): string =>
  s === "ai" ? "🤖" : s === "import" ? "⬇️" : s === "persona" ? "🎭" : "✍️";

const sourceTitle = (s: PhraseSource): string =>
  s === "ai"
    ? "ИИ-слоп (контент-дроп)"
    : s === "import"
      ? "Из снапшота"
      : s === "persona"
        ? "Из персоналии"
        : "Заведена вручную";

export default function ReasonsEditor({
  initial,
  isPending,
  placeholder = "новая фраза…",
  emptyHint = "Пусто — будет использован дефолт из кода.",
  onSave,
  useCounts,
  onResetCounts,
  resetCountsPending = false,
  onSetCount,
  meta,
  onSetMeta,
  onBulkMeta,
}: ReasonsEditorProps) {
  const [list, setList] = useState<string[]>(initial);
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState("");

  useEffect(() => {
    setList(initial);
  }, [initial]);

  const dirty = JSON.stringify(list) !== JSON.stringify(initial);
  const metaEnabled = meta !== undefined;

  const srcOf = (p: string): PhraseSource => meta?.[p]?.source ?? "manual";
  const hiddenOf = (p: string): boolean => !!meta?.[p]?.hidden;

  const stats = useMemo(() => {
    let ai = 0;
    let hidden = 0;
    for (const p of list) {
      if (srcOf(p) === "ai") ai += 1;
      if (hiddenOf(p)) hidden += 1;
    }
    return { ai, hidden };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list, meta]);

  const rows = useMemo(() => {
    return list
      .map((phrase, index) => ({ phrase, index }))
      .filter(({ phrase }) => {
        if (!metaEnabled) return filter === "all";
        if (filter === "hidden") return hiddenOf(phrase);
        if (filter === "ai") return srcOf(phrase) === "ai";
        if (filter === "mine") return srcOf(phrase) !== "ai";
        return true;
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list, filter, meta, metaEnabled]);

  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (list.includes(v)) {
      haptic("warning");
      return;
    }
    setList([...list, v]);
    setDraft("");
    haptic("selection");
  };

  const remove = (i: number) => {
    haptic("warning");
    setList(list.filter((_, j) => j !== i));
    if (editingIndex === i) setEditingIndex(null);
  };

  const startEdit = (i: number) => {
    haptic("selection");
    setEditingIndex(i);
    setEditDraft(list[i]);
  };

  const commitEdit = () => {
    if (editingIndex === null) return;
    const v = editDraft.trim();
    if (!v) return;
    const clash = list.some((p, j) => p === v && j !== editingIndex);
    if (clash) {
      haptic("warning");
      return;
    }
    const prev = list[editingIndex];
    setList(list.map((p, j) => (j === editingIndex ? v : p)));
    setEditingIndex(null);
    haptic("success");
    // J.2: метаданные привязаны к тексту фразы — при правке переносим их на
    // новый текст, иначе поправленная ИИ-фраза теряла бы бейдж и флаг скрытия.
    // Запись по старому тексту остаётся «сиротой» и в UI не видна (пула в ней
    // уже нет) — на ротацию фраз она не влияет.
    const m = meta?.[prev];
    if (onSetMeta && metaEnabled && prev !== v && m) {
      onSetMeta(v, { source: m.source, hidden: m.hidden });
    }
  };

  const filteredPhrases = rows.map((r) => r.phrase);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
          className="flex-1 rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text placeholder:text-tg-hint outline-none border border-transparent focus:border-tg-link"
        />
        <button
          type="button"
          onClick={add}
          disabled={!draft.trim()}
          className="min-h-11 min-w-11 rounded-md bg-tg-link/15 px-2 text-xs text-tg-link disabled:opacity-40"
        >
          + добавить
        </button>
      </div>

      {metaEnabled && (
        <>
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            {(
              [
                ["all", `Все (${list.length})`],
                ["ai", `🤖 ИИ (${stats.ai})`],
                ["mine", "✍️ Мои"],
                ["hidden", `🚫 Скрытые (${stats.hidden})`],
              ] as Array<[Filter, string]>
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => {
                  haptic("selection");
                  setFilter(key);
                }}
                className={`rounded-full px-2 py-1 transition ${
                  filter === key
                    ? "bg-tg-button text-tg-button-text font-medium"
                    : "bg-tg-bg/70 text-tg-hint"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {onBulkMeta && filteredPhrases.length > 0 && (
            <div className="flex flex-wrap gap-1.5 text-[11px]">
              <button
                type="button"
                onClick={() => {
                  haptic("medium");
                  onBulkMeta(filteredPhrases, { hidden: true });
                }}
                className="rounded-md bg-status-busy/15 px-2 py-1 text-status-busy"
              >
                🚫 Скрыть показанные ({filteredPhrases.length})
              </button>
              <button
                type="button"
                onClick={() => {
                  haptic("medium");
                  onBulkMeta(filteredPhrases, { hidden: false });
                }}
                className="rounded-md bg-tg-link/15 px-2 py-1 text-tg-link"
              >
                👁 Показать показанные
              </button>
              {filter !== "ai" && stats.ai > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    haptic("medium");
                    onBulkMeta(
                      list.filter((p) => srcOf(p) === "ai"),
                      { hidden: true },
                    );
                  }}
                  className="rounded-md bg-tg-bg/70 px-2 py-1 text-tg-hint"
                >
                  🤖 Скрыть весь ИИ
                </button>
              )}
            </div>
          )}
        </>
      )}

      <div className="max-h-72 overflow-y-auto rounded-lg bg-tg-bg/40 divide-y divide-tg-secondary-bg/40">
        {list.length === 0 ? (
          <div className="px-2 py-3 text-xs text-tg-hint text-center">{emptyHint}</div>
        ) : rows.length === 0 ? (
          <div className="px-2 py-3 text-xs text-tg-hint text-center">
            Ничего не подходит под фильтр.
          </div>
        ) : (
          rows.map(({ phrase: r, index: i }) => {
            const count = useCounts?.[r] ?? 0;
            const isHidden = hiddenOf(r);
            const src = srcOf(r);
            const isEditing = editingIndex === i;
            return (
              <div key={`${i}:${r}`} className="px-2 py-1.5">
                <div className="flex items-start gap-2">
                  <div className="text-[10px] text-tg-hint w-6 tabular-nums pt-0.5 shrink-0">
                    {i + 1}
                  </div>
                  {isEditing ? (
                    <div className="flex-1 space-y-1">
                      <textarea
                        value={editDraft}
                        onChange={(e) => setEditDraft(e.target.value)}
                        rows={2}
                        className="w-full rounded-md bg-tg-bg/70 px-2 py-1 text-sm text-tg-text outline-none border border-tg-link resize-y"
                      />
                      <div className="flex flex-wrap gap-1.5">
                        <button
                          type="button"
                          onClick={commitEdit}
                          disabled={!editDraft.trim()}
                          className="min-h-11 rounded-md bg-tg-button px-3 py-1 text-xs font-medium text-tg-button-text disabled:opacity-40"
                        >
                          ✓ ОК
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditingIndex(null)}
                          className="min-h-11 rounded-md bg-tg-bg/70 px-3 py-1 text-xs text-tg-hint"
                        >
                          отмена
                        </button>
                        {/* DESIGN_SYSTEM §6: удаление живёт ТОЛЬКО в режиме правки.
                            Раньше ✕ стояла вплотную к 👁/✎ в 36px-кнопках —
                            слишком легко снести фразу вместо скрытия. */}
                        <button
                          type="button"
                          onClick={() => remove(i)}
                          className="min-h-11 rounded-md bg-status-busy/15 px-3 py-1 text-xs text-status-busy"
                          title="Удалить фразу"
                        >
                          ✕ Удалить
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div
                      className={`flex-1 text-sm whitespace-pre-wrap break-words ${
                        isHidden ? "text-tg-hint line-through" : "text-tg-text"
                      }`}
                    >
                      {r}
                    </div>
                  )}
                  {!isEditing && (
                    <div className="flex items-center gap-1 shrink-0 pt-0.5">
                      {metaEnabled && (
                        <button
                          type="button"
                          disabled={!onSetMeta}
                          onClick={() => {
                            haptic("selection");
                            // Тап по бейджу — «оставить/снять метку ИИ». Это
                            // главный жест при разборе дропа: листаешь фильтр
                            // «🤖 ИИ», что зашло — переводишь в «мои», остальное
                            // скрываешь пачкой.
                            onSetMeta?.(r, {
                              source: src === "ai" ? "manual" : "ai",
                            });
                          }}
                          title={
                            src === "ai"
                              ? "ИИ-слоп — нажми, чтобы оставить как «мою» фразу"
                              : `${sourceTitle(src)} — нажми, чтобы пометить как ИИ-слоп`
                          }
                          className="min-h-11 rounded-md bg-tg-bg/70 px-1.5 text-xs disabled:opacity-100"
                        >
                          {sourceIcon(src)}
                        </button>
                      )}
                      {useCounts !== undefined &&
                        (onSetCount && count > 0 && initial.includes(r) ? (
                          <button
                            type="button"
                            onClick={() => {
                              haptic("warning");
                              onSetCount(r, 0);
                            }}
                            className="text-[10px] text-tg-hint tabular-nums rounded px-1 py-0.5 hover:bg-tg-secondary-bg/60 active:scale-95 transition"
                            title={`Использовано ${count} раз${count === 1 ? "" : "а"} — нажми, чтобы сбросить в 0`}
                          >
                            use:{count} ↺
                          </button>
                        ) : (
                          <span
                            className="text-[10px] text-tg-hint tabular-nums"
                            title={`Использовано ${count} раз${count === 1 ? "" : "а"}`}
                          >
                            use:{count}
                          </span>
                        ))}
                      <button
                        type="button"
                        onClick={() => startEdit(i)}
                        className="min-h-11 min-w-11 rounded-md bg-tg-bg/70 px-1.5 text-xs text-tg-hint"
                        title="Редактировать"
                      >
                        ✎
                      </button>
                      {metaEnabled && onSetMeta && (
                        <button
                          type="button"
                          onClick={() => {
                            haptic(isHidden ? "selection" : "warning");
                            onSetMeta(r, { hidden: !isHidden });
                          }}
                          className={`min-h-11 min-w-11 rounded-md px-1.5 text-xs ${
                            isHidden
                              ? "bg-status-busy/15 text-status-busy"
                              : "bg-tg-bg/70 text-tg-hint"
                          }`}
                          title={isHidden ? "Вернуть в ротацию" : "Скрыть из ротации"}
                        >
                          {isHidden ? "🚫" : "👁"}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!dirty || isPending}
          onClick={() => {
            haptic("medium");
            onSave(list);
          }}
          className="flex-1 min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
        >
          {isPending && <Spinner />}
          {isPending
            ? "Сохраняем…"
            : dirty
            ? `💾 Сохранить (${list.length})`
            : `✓ Сохранено (${list.length})`}
        </button>
        {dirty && (
          <button
            type="button"
            onClick={() => {
              haptic("warning");
              setList(initial);
            }}
            className="min-h-11 min-w-11 rounded-md bg-tg-bg/70 px-2 text-xs text-tg-hint"
          >
            ↺
          </button>
        )}
      </div>

      {onResetCounts && (
        <button
          type="button"
          disabled={resetCountsPending}
          onClick={() => {
            haptic("warning");
            if (confirm("Сбросить счётчики использования всех фраз?")) {
              onResetCounts();
            }
          }}
          className="w-full min-h-11 rounded-md bg-tg-bg/70 px-2 text-[11px] text-tg-hint disabled:opacity-50 inline-flex items-center justify-center gap-2"
        >
          {resetCountsPending && <Spinner />}
          🔄 Сбросить счётчики использования
        </button>
      )}
    </div>
  );
}
