import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchEmployee } from "@/api/hr";
import { useAppText } from "@/api/texts";
import {
  fetchMaterials,
  refreshMaterial,
  type HrMaterial,
} from "@/api/materials";
import { humanizeApiError } from "@/api/client";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton } from "@/components/Skeleton";
import Icon from "@/components/Icon";
import { haptic, showAlert, WebApp } from "@/tg/webapp";

import { currentLocale, tx as txIn, useTx } from "@/i18n";
/**
 * «Материалы смены»: график, меню и бар из Google Sheets.
 *
 * Таблицу рисуем из снимка на нашем сервере, а не грузим iframe: в России
 * Google часто недоступен, а смена без графика — это не «деградация», это
 * остановка работы. Рядом честная подпись «обновлено …» и предупреждение,
 * если последнее обновление не удалось (показываем последнюю рабочую версию).
 */
export default function MaterialsScreen() {
  const { tx } = useTx();
  const qc = useQueryClient();
  const hint = useAppText(
    "materials.hint",
    tx("График, меню и методички. Показываем копию с сервера — Google открывать не нужно."),
  );
  const materialsQ = useQuery({
    queryKey: ["hr-materials"],
    queryFn: fetchMaterials,
    staleTime: 60_000,
  });
  const meQ = useQuery({ queryKey: ["hr-employee"], queryFn: fetchEmployee });
  const [activeId, setActiveId] = useState<number | null>(null);

  const refresh = useMutation({
    mutationFn: (id: number) => refreshMaterial(id),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData<HrMaterial[]>(["hr-materials"], (prev) =>
        prev ? prev.map((m) => (m.id === data.id ? data : m)) : prev,
      );
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  if (materialsQ.isError) {
    return (
      <ErrorState
        error={materialsQ.error}
        onRetry={() => void materialsQ.refetch()}
      />
    );
  }

  const materials = materialsQ.data ?? [];
  const active =
    materials.find((m) => m.id === activeId) ?? materials[0] ?? null;
  const canRefresh = !!meQ.data?.is_aup || !!meQ.data?.is_admin;

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <h1 className="text-lg font-semibold text-tg-text">{tx("Материалы смены")}</h1>
        <p className="mt-1 text-xs text-tg-hint">{hint}</p>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {materialsQ.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {!materialsQ.isLoading && materials.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Icon name="book" size={34} className="text-tg-hint" />
            <div className="mt-2 text-sm font-medium text-tg-text">{tx("Материалов пока нет")}</div>
            <div className="mt-1 max-w-[280px] text-xs text-tg-hint">{tx("Руководитель добавит таблицы — они появятся здесь.")}</div>
          </div>
        )}

        {materials.length > 0 && (
          <>
            <div className="flex gap-1.5 overflow-x-auto pb-1">
              {materials.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => {
                    haptic("selection");
                    setActiveId(m.id);
                  }}
                  aria-pressed={active?.id === m.id}
                  className={[
                    "min-h-9 shrink-0 rounded-full px-3 text-xs",
                    active?.id === m.id
                      ? "bg-tg-button text-tg-button-text"
                      : "bg-tg-secondary-bg text-tg-hint",
                  ].join(" ")}
                >
                  {m.emoji ? `${m.emoji} ` : ""}
                  {m.title}
                </button>
              ))}
            </div>

            {active && (
              <>
                <div className="flex flex-wrap items-center gap-2 text-xs text-tg-hint">
                  <span>
                    Обновлено: {active.synced_at ? fmtStamp(active.synced_at) : tx("ещё ни разу")}
                  </span>
                  {active.stale && <span className="text-status-maybe">{tx("· устарело")}</span>}
                  {canRefresh && (
                    <button
                      type="button"
                      disabled={refresh.isPending}
                      onClick={() => refresh.mutate(active.id)}
                      className="ml-auto min-h-8 rounded-full bg-tg-secondary-bg px-2.5 text-xs text-tg-text disabled:opacity-50"
                    >
                      {refresh.isPending ? tx("Обновляю…") : tx("⟳ Обновить")}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => openExternal(active.url)}
                    className="min-h-8 rounded-full bg-tg-secondary-bg px-2.5 text-xs text-tg-text"
                  >{tx("Открыть таблицу")}</button>
                </div>

                {active.sync_error && (
                  <div className="rounded-tile bg-status-busy/10 p-2.5 text-xs text-status-busy">
                    Не удалось обновить ({humanizeSheetError(active.sync_error)}).
                    Показываем последнюю рабочую версию.
                  </div>
                )}

                {active.rows.length === 0 ? (
                  <div className="rounded-card bg-tg-secondary-bg/40 p-3 text-xs text-tg-hint">{tx(
                    "Данных ещё нет: таблица не отдала CSV. Проверь, что доступ «всем, у кого есть ссылка».",
                  )}</div>
                ) : (
                  <SheetTable rows={active.rows} columns={active.columns} />
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** Первая строка — заголовок, если в ней нет чисел/дат в большинстве ячеек. */
function looksLikeHeader(row: string[]): boolean {
  const filled = row.filter(Boolean);
  if (filled.length === 0) return false;
  const numeric = filled.filter((cell) => /^[\d\s.,:%+-]+$/.test(cell)).length;
  return numeric <= filled.length / 2;
}

function SheetTable({
  rows,
  columns,
}: {
  rows: string[][];
  columns: number;
}) {
  const { tx } = useTx();
  const header = useMemo(() => (rows.length > 0 && looksLikeHeader(rows[0]) ? rows[0] : null), [rows]);
  const body = header ? rows.slice(1) : rows;

  return (
    <div className="overflow-x-auto rounded-card border border-tg-secondary-bg">
      <table className="min-w-full border-collapse text-xs">
        <caption className="sr-only">{tx("Таблица материалов смены")}</caption>
        {header && (
          <thead>
            <tr>
              {header.map((cell, index) => (
                <th
                  key={index}
                  scope="col"
                  className="sticky top-0 whitespace-nowrap border-b border-tg-secondary-bg bg-tg-bg px-2 py-1.5 text-left font-semibold text-tg-text"
                >
                  {cell || "—"}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {body.map((row, r) => (
            <tr key={r} className="odd:bg-tg-secondary-bg/30">
              {Array.from({ length: columns }).map((_, c) => (
                <td
                  key={c}
                  className="whitespace-pre-wrap border-b border-tg-secondary-bg/60 px-2 py-1.5 align-top text-tg-text"
                >
                  {row[c] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmtStamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function humanizeSheetError(code: string): string {
  const locale = currentLocale();
  if (code === "access_denied") {
    return txIn(locale, "нет доступа к таблице");
  }
  if (code.startsWith("http_")) {
    return txIn(locale, "Google ответил {code}", { code: code.slice(5) });
  }
  if (code.startsWith("network:")) {
    return txIn(locale, "сервер не достучался до Google");
  }
  return code;
}

function openExternal(url: string) {
  const app = WebApp as unknown as {
    openLink?: (url: string) => void;
  };
  if (app.openLink) app.openLink(url);
  else window.open(url, "_blank", "noopener,noreferrer");
}
