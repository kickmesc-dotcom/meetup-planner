import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  fetchPhrasesSnapshot,
  importPhrasesSnapshot,
  type PhraseSnapshot,
  type SnapshotImportSummary,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

// Дружелюбные подписи пулов для превью/итогов.
const POOL_LABELS: Record<string, string> = {
  loser_reasons: "🤡 Причины лоха",
  chukhan_reasons: "💩 Причины чухана",
  advice: "🔮 Советы",
  media_single: "🎭 Реакт-фразы (мем)",
  media_collection: "🎭 Реакт-фразы (подборка)",
  media_emoji: "😀 Эмодзи-реакции",
};

const poolLabel = (k: string) => POOL_LABELS[k] ?? k;

function countPools(snap: PhraseSnapshot | null): Array<[string, number]> {
  if (!snap?.pools) return [];
  return Object.entries(snap.pools).map(([k, v]) => [k, v.length]);
}

export default function PhrasesSnapshotScreen({ onBack }: Props) {
  // --- Экспорт ---
  const snapshot = useQuery({
    queryKey: ["admin", "phrases-snapshot"],
    queryFn: fetchPhrasesSnapshot,
    staleTime: 10_000,
  });

  const exportText = useMemo(
    () => (snapshot.data ? JSON.stringify(snapshot.data, null, 2) : ""),
    [snapshot.data],
  );

  const onCopy = async () => {
    if (!exportText) return;
    try {
      await navigator.clipboard.writeText(exportText);
      haptic("success");
      void showAlert("Снапшот скопирован в буфер 📋\nСохрани его в надёжное место.");
    } catch {
      haptic("error");
      void showAlert("Не получилось скопировать — выдели текст вручную.");
    }
  };

  const onDownload = () => {
    if (!exportText) return;
    try {
      const blob = new Blob([exportText], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "meetup-phrases-snapshot.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      haptic("success");
    } catch {
      haptic("error");
      void showAlert("Скачивание не сработало (в Telegram бывает) — используй «копировать».");
    }
  };

  // --- Импорт ---
  const [importRaw, setImportRaw] = useState("");
  const [mode, setMode] = useState<"replace" | "merge">("merge");

  const parsed = useMemo<{ data: PhraseSnapshot | null; error: string | null }>(() => {
    const t = importRaw.trim();
    if (!t) return { data: null, error: null };
    try {
      const obj = JSON.parse(t);
      if (obj?.format !== "meetup-planner.phrase-snapshot") {
        return { data: null, error: "Это не снапшот (нет маркера format)." };
      }
      return { data: obj as PhraseSnapshot, error: null };
    } catch {
      return { data: null, error: "Невалидный JSON." };
    }
  }, [importRaw]);

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setImportRaw(String(reader.result ?? ""));
    reader.onerror = () => void showAlert("Не удалось прочитать файл.");
    reader.readAsText(file);
  };

  const doImport = useMutation({
    mutationFn: () => importPhrasesSnapshot(parsed.data, mode),
    onSuccess: (summary: SnapshotImportSummary) => {
      haptic("success");
      void snapshot.refetch();
      const pools = Object.entries(summary.pools)
        .map(([k, v]) => `• ${poolLabel(k)}: ${v.count}`)
        .join("\n");
      const persona =
        summary.personas?.restored != null
          ? `\n🎭 Персонажи: восстановлено ${summary.personas.restored}` +
            (summary.personas.skipped ? `, пропущено ${summary.personas.skipped}` : "")
          : "";
      void showAlert(
        `✅ Импорт (${summary.mode === "replace" ? "замена" : "слияние"}):\n${pools}${persona}`,
      );
      setImportRaw("");
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  return (
    <SubScreen
      title="🗄 Снапшот фраз"
      subtitle="Бэкап причин / реакций / типажей"
      onBack={onBack}
    >
      {/* Экспорт */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-base font-semibold">📤 Экспорт (бэкап)</div>
        <div className="text-xs text-tg-hint">
          Полный слепок всех пулов фраз, счётчиков и типажей. Скопируй или скачай и
          сохрани — это страховка от потери при апдейте.
        </div>
        {snapshot.isPending ? (
          <div className="flex items-center gap-2 text-sm text-tg-hint">
            <Spinner /> Собираем снапшот…
          </div>
        ) : snapshot.isError ? (
          <div className="rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {humanizeApiError(snapshot.error)}
          </div>
        ) : (
          <>
            <div className="rounded-lg bg-tg-bg/40 p-2 text-xs text-tg-text space-y-0.5">
              {countPools(snapshot.data ?? null).map(([k, n]) => (
                <div key={k} className="flex justify-between">
                  <span>{poolLabel(k)}</span>
                  <span className="tabular-nums text-tg-hint">{n}</span>
                </div>
              ))}
              <div className="flex justify-between">
                <span>🎭 Типажи</span>
                <span className="tabular-nums text-tg-hint">
                  {snapshot.data?.personas.length ?? 0}
                </span>
              </div>
            </div>
            <textarea
              readOnly
              value={exportText}
              onFocus={(e) => e.currentTarget.select()}
              className="w-full h-28 rounded-md bg-tg-bg/70 p-2 text-[10px] font-mono text-tg-text outline-none resize-none"
            />
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onCopy}
                className="flex-1 min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text active:scale-[0.98] transition-transform"
              >
                📋 Копировать
              </button>
              <button
                type="button"
                onClick={onDownload}
                className="min-h-11 rounded-lg bg-tg-link/15 px-3 text-sm text-tg-link active:scale-95 transition-transform"
              >
                💾 Файл
              </button>
            </div>
          </>
        )}
      </section>

      {/* Импорт */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-base font-semibold">📥 Импорт (восстановление)</div>
        <div className="text-xs text-tg-hint">
          Вставь снапшот или загрузи файл. <b>Замена</b> — перезаписать пулы целиком
          (как «откатиться к бэкапу»). <b>Слияние</b> — дописать новые фразы без
          дублей. Счётчики и типажи переносятся при замене.
        </div>

        <textarea
          value={importRaw}
          onChange={(e) => setImportRaw(e.target.value)}
          placeholder="Вставь сюда JSON снапшота…"
          className="w-full h-24 rounded-md bg-tg-bg/70 p-2 text-[10px] font-mono text-tg-text placeholder:text-tg-hint outline-none resize-none border border-transparent focus:border-tg-link"
        />

        <label className="block">
          <span className="text-xs text-tg-link cursor-pointer">📁 …или загрузить файл</span>
          <input type="file" accept="application/json,.json" onChange={onFile} className="hidden" />
        </label>

        {parsed.error && (
          <div className="rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {parsed.error}
          </div>
        )}

        {parsed.data && (
          <>
            <div className="rounded-lg bg-tg-bg/40 p-2 text-xs text-tg-text space-y-0.5">
              <div className="text-tg-hint mb-1">Превью снапшота:</div>
              {countPools(parsed.data).map(([k, n]) => (
                <div key={k} className="flex justify-between">
                  <span>{poolLabel(k)}</span>
                  <span className="tabular-nums text-tg-hint">{n}</span>
                </div>
              ))}
              <div className="flex justify-between">
                <span>🎭 Типажи</span>
                <span className="tabular-nums text-tg-hint">{parsed.data.personas.length}</span>
              </div>
            </div>

            <div className="flex gap-2">
              {(["merge", "replace"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => {
                    haptic("selection");
                    setMode(m);
                  }}
                  className={`flex-1 min-h-9 rounded-md px-2 text-xs transition ${
                    mode === m
                      ? "bg-tg-button text-tg-button-text font-medium"
                      : "bg-tg-bg/70 text-tg-hint"
                  }`}
                >
                  {m === "merge" ? "🔀 Слияние" : "♻️ Замена"}
                </button>
              ))}
            </div>

            <button
              type="button"
              disabled={doImport.isPending}
              onClick={() => {
                haptic("medium");
                const warn =
                  mode === "replace"
                    ? "Заменить ВСЕ пулы фраз содержимым снапшота? Текущие будут перезаписаны."
                    : "Дописать фразы из снапшота к текущим (без дублей)?";
                if (confirm(warn)) doImport.mutate();
              }}
              className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
            >
              {doImport.isPending && <Spinner />}
              {doImport.isPending ? "Применяем…" : "Применить снапшот"}
            </button>
          </>
        )}
      </section>
    </SubScreen>
  );
}
