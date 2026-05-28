import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createProxy,
  deleteProxy,
  fetchProxies,
  fetchProxyMode,
  patchProxy,
  proxyAlertsGet,
  proxyAlertsSet,
  proxyBootstrapFetch,
  proxyClearAddErrors,
  proxyClearLastError,
  proxyDeleteDead,
  proxyGetAddErrors,
  proxyParse,
  proxyPing,
  proxyPingAll,
  proxySelftest,
  proxyStatus,
  updateProxyEnabled,
  updateProxyMode,
  type ProxyAddErrorItem,
  type ProxyAddResult,
  type ProxyDraft,
  type ProxyEntry,
  type ProxyMode,
  type ProxyType,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import { Toggle } from "@/components/Checkbox";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

const MODE_LABELS: Record<ProxyMode, string> = {
  always_on: "🔗 Только через прокси",
  always_off: "📡 Direct (без прокси)",
  auto_fallback: "♻️ Auto-fallback (direct → прокси при проблеме)",
};

const MODE_HINTS: Record<ProxyMode, string> = {
  always_on:
    "Каждый запрос — через прокси. Если все прокси умерли, бот падает и админ получает алёрт.",
  always_off: "Прокси не используется. Хорошо когда сеть из РФ открыта.",
  auto_fallback:
    "Сначала direct. При сетевой ошибке — следующий живой прокси из пула. Самотест раз в 10 мин.",
};

export default function ProxyScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const modeQ = useQuery({ queryKey: ["admin", "proxy-mode"], queryFn: fetchProxyMode });
  const listQ = useQuery({ queryKey: ["admin", "proxies"], queryFn: fetchProxies });
  const statusQ = useQuery({
    queryKey: ["admin", "proxy-status"],
    queryFn: proxyStatus,
    refetchInterval: 5 * 60 * 1000, // 5 мин — мягкий автотест
    staleTime: 30 * 1000,
  });
  const alertsQ = useQuery({
    queryKey: ["admin", "proxy-alerts"],
    queryFn: proxyAlertsGet,
  });

  // --- mutations ---

  const setMode = useMutation({
    mutationFn: updateProxyMode,
    onMutate: async (next) => {
      await qc.cancelQueries({ queryKey: ["admin", "proxy-mode"] });
      const prev = qc.getQueryData<{ mode: ProxyMode }>(["admin", "proxy-mode"]);
      qc.setQueryData(["admin", "proxy-mode"], { mode: next });
      return { prev };
    },
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "proxy-mode"] });
      qc.invalidateQueries({ queryKey: ["admin", "proxy-status"] });
    },
    onError: (e, _vars, ctx) => {
      haptic("error");
      if (ctx?.prev) qc.setQueryData(["admin", "proxy-mode"], ctx.prev);
      void showAlert(humanizeApiError(e));
    },
  });

  const setEnabled = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      updateProxyEnabled(id, enabled),
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "proxies"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const del = useMutation({
    mutationFn: deleteProxy,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "proxies"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  // GHG6 E1.2/E1.3: после добавления показываем результат ping'а одним баннером
  // прямо в этом экране (а не отдельным alert'ом), и инвалидируем ring-buffer
  // ошибок — там может прибавиться запись, если упало.
  const [lastAdd, setLastAdd] = useState<ProxyAddResult | null>(null);

  const add = useMutation({
    mutationFn: createProxy,
    onSuccess: (data) => {
      haptic(data.ping_result?.ok === false ? "warning" : "success");
      setLastAdd(data);
      qc.invalidateQueries({ queryKey: ["admin", "proxies"] });
      qc.invalidateQueries({ queryKey: ["admin", "proxy-add-errors"] });
    },
    onError: (e) => {
      haptic("error");
      setLastAdd(null);
      qc.invalidateQueries({ queryKey: ["admin", "proxy-add-errors"] });
      void showAlert(humanizeApiError(e));
    },
  });

  // GHG6 E1.1: лента ошибок добавления (ring-buffer 20). Раздел рендерится
  // только если буфер не пуст.
  const addErrorsQ = useQuery({
    queryKey: ["admin", "proxy-add-errors"],
    queryFn: proxyGetAddErrors,
    staleTime: 30 * 1000,
  });

  const clearAddErrors = useMutation({
    mutationFn: proxyClearAddErrors,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "proxy-add-errors"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  // GHG6 E1.4: bootstrap-fetch публичного списка прокси.
  const bootstrap = useMutation({
    mutationFn: () => proxyBootstrapFetch(),
    onSuccess: (data) => {
      haptic(data.added > 0 ? "success" : "warning");
      qc.invalidateQueries({ queryKey: ["admin", "proxies"] });
      qc.invalidateQueries({ queryKey: ["admin", "proxy-add-errors"] });
      void showAlert(
        `Источник: ${data.source_url || "—"}\n` +
          `Найдено: ${data.fetched}, живых: ${data.pinged_alive}, добавлено: ${data.added}.\n` +
          `Пропущено: дубли ${data.skipped_duplicate}, мёртвые ${data.skipped_dead}, пул полон ${data.skipped_pool_full}.` +
          (data.errors.length ? `\nОшибки: ${data.errors.join(", ")}` : ""),
      );
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const selftest = useMutation({
    mutationFn: proxySelftest,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "proxy-status"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const pingOne = useMutation({
    mutationFn: proxyPing,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "proxies"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const pingAllM = useMutation({
    mutationFn: proxyPingAll,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "proxies"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const delDead = useMutation({
    mutationFn: proxyDeleteDead,
    onSuccess: (data) => {
      haptic("warning");
      void showAlert(`Удалено: ${data.deleted}`);
      qc.invalidateQueries({ queryKey: ["admin", "proxies"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const clearErr = useMutation({
    mutationFn: proxyClearLastError,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "proxy-status"] });
    },
  });

  const setAlerts = useMutation({
    mutationFn: proxyAlertsSet,
    onMutate: async (next) => {
      await qc.cancelQueries({ queryKey: ["admin", "proxy-alerts"] });
      const prev = qc.getQueryData(["admin", "proxy-alerts"]);
      qc.setQueryData(["admin", "proxy-alerts"], (old: any) =>
        old ? { ...old, enabled: next } : { enabled: next, last_alert_at: null },
      );
      return { prev };
    },
    onSuccess: () => haptic("selection"),
    onError: (_e, _v, ctx) => {
      haptic("error");
      if (ctx?.prev) qc.setQueryData(["admin", "proxy-alerts"], ctx.prev);
    },
  });

  // --- sort state ---
  const [sortBySpeed, setSortBySpeed] = useState(false);
  const sortedList = useMemo<ProxyEntry[]>(() => {
    if (!listQ.data) return [];
    if (!sortBySpeed) return listQ.data;
    const arr = [...listQ.data];
    arr.sort((a, b) => {
      // dead в конец, неотвечавшие — в середину
      const deadA = a.dead_until && new Date(a.dead_until) > new Date() ? 1 : 0;
      const deadB = b.dead_until && new Date(b.dead_until) > new Date() ? 1 : 0;
      if (deadA !== deadB) return deadA - deadB;
      const aOk = a.last_ok_at ? new Date(a.last_ok_at).getTime() : 0;
      const bOk = b.last_ok_at ? new Date(b.last_ok_at).getTime() : 0;
      // более свежий ok — выше (быстрый прокси проявляется через свежий last_ok_at)
      return bOk - aOk;
    });
    return arr;
  }, [listQ.data, sortBySpeed]);

  // --- collapsible pool ---
  const [poolOpen, setPoolOpen] = useState<boolean>(() => (listQ.data?.length ?? 0) <= 5);

  // --- editing state ---
  const [editingId, setEditingId] = useState<number | null>(null);

  return (
    <SubScreen
      title="🌐 Прокси"
      subtitle="Пул прокси, индикаторы и парсер из @ProxyMTProto"
      onBack={onBack}
    >
      {/* === Индикаторы === */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
        <StatusBadge statusQ={statusQ} />
        <SelftestCard
          last={statusQ.data?.last_selftest ?? null}
          isRunning={selftest.isPending}
          onRun={() => selftest.mutate()}
        />
        {statusQ.data?.last_error && (
          <LastErrorCard
            error={statusQ.data.last_error}
            onClear={() => clearErr.mutate()}
          />
        )}
      </section>

      {/* === Режим === */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-base font-semibold">Режим</div>
        {modeQ.isPending || !modeQ.data ? (
          <ListSkeleton rows={1} />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-1.5">
              {(Object.keys(MODE_LABELS) as ProxyMode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => {
                    haptic("selection");
                    setMode.mutate(m);
                  }}
                  className={[
                    "min-h-11 rounded-lg px-3 py-2 text-sm text-left transition-colors",
                    modeQ.data.mode === m
                      ? "bg-tg-link/20 text-tg-link border border-tg-link/40"
                      : "bg-tg-bg/50 text-tg-text border border-transparent",
                  ].join(" ")}
                >
                  {MODE_LABELS[m]}
                </button>
              ))}
            </div>
            <div className="text-xs text-tg-hint pt-1">
              {MODE_HINTS[modeQ.data.mode]}
            </div>
          </>
        )}
      </section>

      {/* === Алёрты === */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="text-base font-semibold">🔔 Уведомлять админа</div>
            <div className="text-xs text-tg-hint">
              В личку при падении всех прокси. Не чаще 1 раза в час.
              {alertsQ.data?.last_alert_at && (
                <>
                  {" "}
                  Последний алёрт:{" "}
                  <span className="text-tg-text">
                    {new Date(alertsQ.data.last_alert_at).toLocaleString()}
                  </span>
                </>
              )}
            </div>
          </div>
          <Toggle
            checked={alertsQ.data?.enabled ?? true}
            onChange={(v) => setAlerts.mutate(v)}
            highlight={false}
          />
        </div>
      </section>

      {/* === Добавление через парсер === */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-base font-semibold">Добавить прокси</div>
        <div className="text-xs text-tg-hint">
          Вставь сюда блок из <b>@ProxyMTProto</b> (можно несколько подряд) или
          раскрой «Ввести вручную».
        </div>
        <ParserBox
          onParse={async (text) => {
            const res = await proxyParse(text);
            return res.parsed;
          }}
          onAdd={(draft) =>
            add.mutateAsync({
              server: draft.server,
              port: draft.port,
              type: draft.type,
              secret: draft.secret,
            })
          }
        />
        <details className="rounded-md bg-tg-bg/30 p-2">
          <summary className="text-xs text-tg-link cursor-pointer select-none">
            Ввести вручную (IP / port / type / secret)
          </summary>
          <div className="pt-2">
            <AddProxyForm
              isPending={add.isPending}
              onSubmit={(body) => add.mutate(body)}
            />
          </div>
        </details>

        {/* GHG6 E1.2/E1.3: баннер с результатом последнего add (ping_result). */}
        {lastAdd && (
          <AddResultBanner result={lastAdd} onDismiss={() => setLastAdd(null)} />
        )}

        {/* GHG6 E1.4: bootstrap-fetch публичного списка прокси. */}
        <button
          type="button"
          disabled={bootstrap.isPending}
          onClick={() => {
            haptic("medium");
            bootstrap.mutate();
          }}
          className="w-full min-h-10 rounded-md bg-tg-button/80 px-3 py-2 text-sm text-tg-button-text disabled:opacity-50 inline-flex items-center justify-center gap-2"
          title="Скачать публичный список прокси, пингануть и добавить живые"
        >
          {bootstrap.isPending && <Spinner />}
          🌐 Найти живые прокси
        </button>
      </section>

      {/* GHG6 E1.1: collapsible раздел «Ошибки добавления». Рендерится только
          если ring-buffer непустой. */}
      {(addErrorsQ.data?.errors.length ?? 0) > 0 && (
        <AddErrorsSection
          errors={addErrorsQ.data!.errors}
          onClear={() => clearAddErrors.mutate()}
          isClearing={clearAddErrors.isPending}
        />
      )}

      {/* === Пул === */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPoolOpen((v) => !v)}
            className="flex-1 text-left text-base font-semibold flex items-center gap-2"
          >
            <span>{poolOpen ? "▼" : "▶"}</span>
            <span>
              Пул прокси {listQ.data ? `(${listQ.data.length}/50)` : ""}
            </span>
          </button>
          {poolOpen && (
            <>
              <button
                type="button"
                disabled={pingAllM.isPending || !listQ.data?.length}
                onClick={() => {
                  haptic("medium");
                  pingAllM.mutate();
                }}
                className="min-h-9 rounded-md bg-tg-button/80 px-2 text-xs text-tg-button-text disabled:opacity-50 inline-flex items-center gap-1"
                title="Пинг всех (медленно)"
              >
                {pingAllM.isPending && <Spinner />}
                Ping all
              </button>
              <button
                type="button"
                disabled={delDead.isPending || !listQ.data?.length}
                onClick={() => {
                  if (confirm("Удалить прокси, которые при проверке выдали ошибку и не отвечали успехом?")) {
                    haptic("warning");
                    delDead.mutate();
                  }
                }}
                className="min-h-9 rounded-md bg-status-busy/20 px-2 text-xs text-status-busy disabled:opacity-50"
                title="Удалить мёртвые"
              >
                🗑 dead
              </button>
              <button
                type="button"
                onClick={() => setSortBySpeed((v) => !v)}
                className={[
                  "min-h-9 rounded-md px-2 text-xs",
                  sortBySpeed ? "bg-tg-link/20 text-tg-link" : "bg-tg-bg/50 text-tg-text",
                ].join(" ")}
                title="Сортировать по скорости (свежее last_ok сверху)"
              >
                ↕ speed
              </button>
            </>
          )}
        </div>
        {poolOpen && (
          <>
            {listQ.isPending || !listQ.data ? (
              <ListSkeleton rows={3} />
            ) : sortedList.length === 0 ? (
              <div className="text-xs text-tg-hint text-center py-3">
                Пусто. Бот ходит direct.
              </div>
            ) : (
              <div className="space-y-2">
                {sortedList.map((p) => (
                  <ProxyRow
                    key={p.id}
                    p={p}
                    editing={editingId === p.id}
                    onToggle={(enabled) => setEnabled.mutate({ id: p.id, enabled })}
                    onDelete={() => {
                      if (confirm(`Удалить ${p.server}:${p.port}?`)) del.mutate(p.id);
                    }}
                    onPing={() => pingOne.mutate(p.id)}
                    onEditStart={() => setEditingId(p.id)}
                    onEditCancel={() => setEditingId(null)}
                    onEditSave={async (patch) => {
                      await patchProxy(p.id, patch);
                      setEditingId(null);
                      qc.invalidateQueries({ queryKey: ["admin", "proxies"] });
                      haptic("success");
                    }}
                    pingPending={pingOne.isPending && pingOne.variables === p.id}
                    deletePending={del.isPending}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </section>
    </SubScreen>
  );
}

// --- Indicator components ---

function StatusBadge({ statusQ }: { statusQ: ReturnType<typeof useQuery<any, any, any, any>> }) {
  if (statusQ.isPending || !statusQ.data) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <span className="inline-block h-3 w-3 rounded-full bg-tg-hint animate-pulse" />
        <span className="text-tg-hint">Проверяем статус бота…</span>
      </div>
    );
  }
  const ok = statusQ.data.bot_active;
  return (
    <div className="flex items-center gap-2 text-sm">
      <span
        className={`inline-block h-3 w-3 rounded-full ${
          ok ? "bg-status-free" : "bg-status-busy"
        }`}
      />
      <span className="font-medium">{ok ? "Бот активен" : "Бот недоступен"}</span>
      <span className="text-xs text-tg-hint ml-auto">
        режим: <b className="text-tg-text">{statusQ.data.mode}</b>
        {statusQ.data.pool_size > 0 && (
          <>
            {" "}· пул: <b className="text-tg-text">{statusQ.data.alive_count}/{statusQ.data.pool_size}</b>
          </>
        )}
      </span>
    </div>
  );
}

function SelftestCard({
  last,
  isRunning,
  onRun,
}: {
  last: {
    ok: boolean;
    mode_used: string;
    proxy_id: number | null;
    latency_ms: number | null;
    error: string | null;
  } | null;
  isRunning: boolean;
  onRun: () => void;
}) {
  const color = !last
    ? "bg-tg-hint"
    : !last.ok
    ? "bg-status-busy"
    : last.latency_ms !== null && last.latency_ms < 800
    ? "bg-status-free"
    : "bg-status-maybe";
  return (
    <div className="rounded-lg bg-tg-bg/40 p-2 space-y-1">
      <div className="flex items-center gap-2">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} />
        <span className="text-sm font-medium">Отправка сообщений</span>
        <button
          type="button"
          disabled={isRunning}
          onClick={() => {
            haptic("medium");
            onRun();
          }}
          className="ml-auto min-h-8 rounded-md bg-tg-button/80 px-2 text-xs text-tg-button-text disabled:opacity-50 inline-flex items-center gap-1"
        >
          {isRunning && <Spinner />}
          🧪 Проверить
        </button>
      </div>
      <div className="text-xs text-tg-hint">
        {!last ? (
          "Проверка ещё не запускалась."
        ) : last.ok ? (
          <>
            ✓ через <b className="text-tg-text">{last.mode_used}</b>
            {last.proxy_id !== null && <> (proxy #{last.proxy_id})</>}
            {last.latency_ms !== null && <>, ~{last.latency_ms} мс</>}
          </>
        ) : (
          <span className="text-status-busy">✗ {last.error || "ошибка"}</span>
        )}
      </div>
    </div>
  );
}

function LastErrorCard({
  error,
  onClear,
}: {
  error: { at: string; message: string; mode_used: string; proxy_id: number | null };
  onClear: () => void;
}) {
  if (!error.message) return null;
  return (
    <div className="rounded-lg bg-status-busy/15 border border-status-busy/40 p-2 space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-status-busy">Последняя ошибка</span>
        <button
          type="button"
          onClick={onClear}
          className="ml-auto min-h-7 min-w-7 rounded-md bg-tg-bg/40 px-1 text-xs text-tg-hint"
          title="Очистить"
        >
          ✕
        </button>
      </div>
      <div className="text-[11px] text-tg-hint">
        {new Date(error.at).toLocaleString()} · {error.mode_used}
        {error.proxy_id !== null && <> · proxy #{error.proxy_id}</>}
      </div>
      <div className="text-xs text-tg-text break-words">{error.message}</div>
    </div>
  );
}

// --- Row ---

function ProxyRow({
  p,
  editing,
  onToggle,
  onDelete,
  onPing,
  onEditStart,
  onEditCancel,
  onEditSave,
  pingPending,
  deletePending,
}: {
  p: ProxyEntry;
  editing: boolean;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
  onPing: () => void;
  onEditStart: () => void;
  onEditCancel: () => void;
  onEditSave: (patch: {
    server?: string;
    port?: number;
    type?: ProxyType;
    secret?: string;
    clear_secret?: boolean;
  }) => Promise<void>;
  pingPending: boolean;
  deletePending: boolean;
}) {
  const dead = p.dead_until && new Date(p.dead_until) > new Date();
  const statusDot = !p.enabled
    ? "bg-tg-hint"
    : dead
    ? "bg-status-busy"
    : p.last_ok_at
    ? "bg-status-free"
    : "bg-status-maybe";
  return (
    <div className="rounded-lg bg-tg-bg/40 p-2 space-y-1">
      <div className="flex items-center gap-2">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${statusDot} shrink-0`} />
        <div className="flex-1 min-w-0">
          <div className="text-sm text-tg-text truncate">
            {p.server}:{p.port}
          </div>
          <div className="text-[10px] text-tg-hint">
            {p.type.toUpperCase()}
            {p.fail_count > 0 ? ` · fails: ${p.fail_count}` : ""}
            {dead ? ` · 💤 до ${new Date(p.dead_until!).toLocaleTimeString()}` : ""}
            {p.last_ok_at ? ` · ✓ ${new Date(p.last_ok_at).toLocaleString()}` : ""}
          </div>
        </div>
        <button
          type="button"
          disabled={pingPending}
          onClick={() => {
            haptic("medium");
            onPing();
          }}
          className="min-h-9 min-w-9 rounded-md bg-tg-bg/50 px-2 text-xs text-tg-text disabled:opacity-50 inline-flex items-center justify-center gap-1"
          title="Ping"
        >
          {pingPending ? <Spinner /> : "📶"}
        </button>
        <button
          type="button"
          onClick={() => (editing ? onEditCancel() : onEditStart())}
          className="min-h-9 min-w-9 rounded-md bg-tg-bg/50 px-2 text-xs text-tg-text"
          title="Edit"
        >
          {editing ? "↩" : "✎"}
        </button>
        <Toggle checked={p.enabled} onChange={onToggle} highlight={false} />
        <button
          type="button"
          disabled={deletePending}
          onClick={() => {
            haptic("warning");
            onDelete();
          }}
          className="min-h-9 min-w-9 rounded-md bg-status-busy/20 px-2 text-xs text-status-busy disabled:opacity-50"
          title="Удалить"
        >
          ✕
        </button>
      </div>
      {editing && (
        <EditRowForm
          p={p}
          onCancel={onEditCancel}
          onSave={onEditSave}
        />
      )}
    </div>
  );
}

function EditRowForm({
  p,
  onCancel,
  onSave,
}: {
  p: ProxyEntry;
  onCancel: () => void;
  onSave: (patch: {
    server?: string;
    port?: number;
    type?: ProxyType;
    secret?: string;
    clear_secret?: boolean;
  }) => Promise<void>;
}) {
  const [server, setServer] = useState(p.server);
  const [port, setPort] = useState(String(p.port));
  const [type, setType] = useState<ProxyType>(p.type);
  const [secret, setSecret] = useState(p.secret ?? "");
  const [saving, setSaving] = useState(false);

  const portN = parseInt(port, 10);
  const valid = server.trim().length > 0 && portN > 0 && portN <= 65535;

  const handleSave = async () => {
    if (!valid) return;
    setSaving(true);
    try {
      const patch: any = {};
      if (server.trim() !== p.server) patch.server = server.trim();
      if (portN !== p.port) patch.port = portN;
      if (type !== p.type) patch.type = type;
      const cur = p.secret ?? "";
      const next = secret.trim();
      if (next !== cur) {
        if (next === "") patch.clear_secret = true;
        else patch.secret = next;
      }
      if (Object.keys(patch).length === 0) {
        onCancel();
        return;
      }
      await onSave(patch);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-2 pt-1 border-t border-tg-bg/50">
      <div className="grid grid-cols-[1fr_88px] gap-2">
        <input
          value={server}
          onChange={(e) => setServer(e.target.value)}
          className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
        />
        <input
          inputMode="numeric"
          value={port}
          onChange={(e) => setPort(e.target.value.replace(/[^0-9]/g, ""))}
          className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text tabular-nums outline-none border border-transparent focus:border-tg-link"
        />
      </div>
      <div className="grid grid-cols-[1fr_1fr] gap-2">
        <select
          value={type}
          onChange={(e) => setType(e.target.value as ProxyType)}
          className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
        >
          <option value="socks5">SOCKS5</option>
          <option value="http">HTTP</option>
          <option value="mtproto">MTProto</option>
        </select>
        <input
          placeholder="secret / pass"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
        />
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!valid || saving}
          onClick={handleSave}
          className="flex-1 min-h-10 rounded-lg bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-40 inline-flex items-center justify-center gap-2"
        >
          {saving && <Spinner />}
          💾 Сохранить
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="min-h-10 rounded-lg bg-tg-bg/50 px-3 text-sm text-tg-text"
        >
          Отмена
        </button>
      </div>
    </div>
  );
}

// --- Parser ---

function ParserBox({
  onParse,
  onAdd,
}: {
  onParse: (text: string) => Promise<ProxyDraft[]>;
  onAdd: (draft: ProxyDraft) => Promise<unknown>;
}) {
  const [text, setText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [drafts, setDrafts] = useState<ProxyDraft[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [adding, setAdding] = useState(false);

  const handleParse = async () => {
    if (!text.trim()) return;
    setParsing(true);
    try {
      const res = await onParse(text);
      setDrafts(res);
      setSelected(new Set(res.map((_, i) => i)));
      if (res.length === 0) {
        void showAlert("Не нашёл ни одной валидной пары Server/Port в тексте.");
      }
    } catch (e) {
      void showAlert(humanizeApiError(e));
    } finally {
      setParsing(false);
    }
  };

  const handleAdd = async () => {
    if (!drafts) return;
    setAdding(true);
    let ok = 0;
    let fail = 0;
    for (let i = 0; i < drafts.length; i++) {
      if (!selected.has(i)) continue;
      try {
        await onAdd(drafts[i]);
        ok += 1;
      } catch {
        fail += 1;
      }
    }
    setAdding(false);
    haptic(ok > 0 ? "success" : "error");
    void showAlert(`Добавлено: ${ok}${fail ? `, пропущено: ${fail}` : ""}`);
    setText("");
    setDrafts(null);
    setSelected(new Set());
  };

  return (
    <div className="space-y-2">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder={"Server: 178.105.137.152\nPort: 443\nSecret: eeabf...\n@ProxyMTProto"}
        className="w-full rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text placeholder:text-tg-hint outline-none border border-transparent focus:border-tg-link font-mono"
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={parsing || !text.trim()}
          onClick={handleParse}
          className="flex-1 min-h-10 rounded-lg bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-40 inline-flex items-center justify-center gap-2"
        >
          {parsing && <Spinner />}
          📋 Распарсить
        </button>
        {drafts && (
          <button
            type="button"
            onClick={() => {
              setText("");
              setDrafts(null);
              setSelected(new Set());
            }}
            className="min-h-10 rounded-lg bg-tg-bg/50 px-3 text-sm text-tg-text"
          >
            Сброс
          </button>
        )}
      </div>
      {drafts && drafts.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-xs text-tg-hint">
            Найдено: {drafts.length}. Снимите галочки, чтобы пропустить.
          </div>
          {drafts.map((d, i) => (
            // GHG7 P1.1: добавлен .chk-tg для контрастной рамки/заливки
            // (раньше нативный input был «чёрное на чёрном» в TG dark theme,
            // непонятно прожат или нет). min-h-11 поднимает hit-target всей
            // строки до 44px по Apple/TG guideline — тыкать пальцем удобно.
            <label
              key={i}
              className="flex items-center gap-2 rounded-md bg-tg-bg/40 px-2 py-1.5 text-sm cursor-pointer min-h-11"
            >
              <input
                type="checkbox"
                className="chk-tg"
                checked={selected.has(i)}
                onChange={(e) => {
                  setSelected((s) => {
                    const next = new Set(s);
                    if (e.target.checked) next.add(i);
                    else next.delete(i);
                    return next;
                  });
                }}
              />
              <span className="text-tg-text truncate">
                {d.server}:{d.port}
              </span>
              <span className="text-[10px] text-tg-hint ml-auto">{d.type}</span>
            </label>
          ))}
          <button
            type="button"
            disabled={adding || selected.size === 0}
            onClick={handleAdd}
            className="w-full min-h-10 rounded-lg bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-40 inline-flex items-center justify-center gap-2"
          >
            {adding && <Spinner />}
            ➕ Добавить выбранные ({selected.size})
          </button>
        </div>
      )}
    </div>
  );
}

// --- Manual add form ---

function AddProxyForm({
  isPending,
  onSubmit,
}: {
  isPending: boolean;
  onSubmit: (body: {
    server: string;
    port: number;
    type: ProxyType;
    secret?: string | null;
  }) => void;
}) {
  const [server, setServer] = useState("");
  const [port, setPort] = useState("443");
  const [type, setType] = useState<ProxyType>("mtproto");
  const [secret, setSecret] = useState("");

  const portN = parseInt(port, 10);
  const valid = server.trim().length > 0 && portN > 0 && portN <= 65535;

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[1fr_88px] gap-2">
        <input
          type="text"
          placeholder="server (IP/host)"
          value={server}
          onChange={(e) => setServer(e.target.value)}
          className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text placeholder:text-tg-hint outline-none border border-transparent focus:border-tg-link"
        />
        <input
          type="text"
          inputMode="numeric"
          placeholder="port"
          value={port}
          onChange={(e) => setPort(e.target.value.replace(/[^0-9]/g, ""))}
          className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text tabular-nums placeholder:text-tg-hint outline-none border border-transparent focus:border-tg-link"
        />
      </div>
      <div className="grid grid-cols-[1fr_1fr] gap-2">
        <select
          value={type}
          onChange={(e) => setType(e.target.value as ProxyType)}
          className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
        >
          <option value="mtproto">MTProto</option>
          <option value="socks5">SOCKS5</option>
          <option value="http">HTTP</option>
        </select>
        <input
          type="text"
          placeholder="secret / pass (опц.)"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text placeholder:text-tg-hint outline-none border border-transparent focus:border-tg-link"
        />
      </div>
      <button
        type="button"
        disabled={!valid || isPending}
        onClick={() => {
          haptic("medium");
          onSubmit({
            server: server.trim(),
            port: portN,
            type,
            secret: secret.trim() || null,
          });
          setServer("");
          setPort("443");
          setSecret("");
        }}
        className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
      >
        {isPending && <Spinner />}
        {isPending ? "Добавляем…" : "➕ Добавить"}
      </button>
    </div>
  );
}

// --- GHG6 E1.2/E1.3: баннер последнего добавления с ping-результатом ---

function AddResultBanner({
  result,
  onDismiss,
}: {
  result: ProxyAddResult;
  onDismiss: () => void;
}) {
  const { proxy, created, ping_result } = result;
  // MTProto не пингуется по HTTP — это «нельзя проверить», не «мёртв».
  const isMtprotoNotChecked =
    ping_result?.error === "ping_not_supported_for_type:mtproto";
  const ok = ping_result?.ok === true;
  const dead = ping_result && ping_result.ok === false && !isMtprotoNotChecked;
  const cls = ok
    ? "bg-status-free/15 text-status-free border-status-free/40"
    : dead
      ? "bg-status-busy/15 text-status-busy border-status-busy/40"
      : "bg-tg-link/15 text-tg-link border-tg-link/40";
  const icon = ok ? "✅" : dead ? "⚠️" : "ℹ️";
  let msg: string;
  if (!ping_result) {
    msg = `${proxy.server}:${proxy.port} ${created ? "добавлен" : "обновлён"} (не пинговали — enabled=false)`;
  } else if (ok) {
    msg = `${proxy.server}:${proxy.port} ${created ? "добавлен" : "обновлён"}, ping ${ping_result.latency_ms}мс`;
  } else if (isMtprotoNotChecked) {
    msg = `${proxy.server}:${proxy.port} ${created ? "добавлен" : "обновлён"}. MTProto не проверяется по HTTP — оценишь по селфтесту/использованию.`;
  } else {
    msg = `${proxy.server}:${proxy.port} ${created ? "добавлен" : "обновлён"}, но не отвечает: ${ping_result.error ?? "unknown"}`;
  }
  return (
    <div
      className={`flex items-start gap-2 rounded-lg border ${cls} px-3 py-2 text-sm`}
    >
      <span className="mt-0.5">{icon}</span>
      <span className="flex-1 min-w-0 break-words">{msg}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="text-current opacity-70 hover:opacity-100"
        title="Скрыть"
      >
        ✕
      </button>
    </div>
  );
}

// --- GHG6 E1.1: ring-buffer ошибок добавления (collapsible) ---

const REASON_LABEL: Record<string, string> = {
  proxy_pool_full: "Пул переполнен",
  db_error: "Ошибка БД",
  validation_error: "Не прошёл валидацию",
};

function AddErrorsSection({
  errors,
  onClear,
  isClearing,
}: {
  errors: ProxyAddErrorItem[];
  onClear: () => void;
  isClearing: boolean;
}) {
  const [open, setOpen] = useState(false);
  // Показываем самые свежие сверху.
  const reversed = [...errors].reverse();
  return (
    <section className="rounded-xl bg-status-busy/10 border border-status-busy/30 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex-1 text-left text-base font-semibold flex items-center gap-2 text-status-busy"
        >
          <span>{open ? "▼" : "▶"}</span>
          <span>🚨 Ошибки добавления ({errors.length})</span>
        </button>
        <button
          type="button"
          disabled={isClearing}
          onClick={() => {
            if (confirm("Очистить ленту ошибок добавления?")) onClear();
          }}
          className="min-h-9 rounded-md bg-status-busy/20 px-2 text-xs text-status-busy disabled:opacity-50 inline-flex items-center gap-1"
        >
          {isClearing && <Spinner />}✕ Очистить
        </button>
      </div>
      {open && (
        <ul className="space-y-1 text-xs">
          {reversed.map((e, i) => {
            const d = e.draft || {};
            const where =
              typeof d.server === "string" && typeof d.port === "number"
                ? `${d.server}:${d.port}${typeof d.type === "string" ? ` (${d.type})` : ""}`
                : "—";
            return (
              <li
                key={`${e.at}-${i}`}
                className="rounded-md bg-tg-bg/60 px-2 py-1.5 text-tg-text"
              >
                <div className="flex items-center justify-between gap-2 tabular-nums">
                  <span className="font-semibold text-status-busy">
                    {REASON_LABEL[e.reason] ?? e.reason}
                  </span>
                  <span className="text-tg-hint">
                    {new Date(e.at).toLocaleString()}
                  </span>
                </div>
                <div className="text-tg-hint break-all">{where}</div>
                {e.detail && (
                  <div className="text-tg-hint italic break-all">{e.detail}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
