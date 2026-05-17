import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createProxy,
  deleteProxy,
  fetchProxies,
  fetchProxyMode,
  updateProxyEnabled,
  updateProxyMode,
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
  always_on: "🔗 Всегда через прокси",
  always_off: "📡 Только direct",
  auto_fallback: "♻️ Авто-фолбэк (direct → прокси при ошибке)",
};

export default function ProxyScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const modeQ = useQuery({ queryKey: ["admin", "proxy-mode"], queryFn: fetchProxyMode });
  const listQ = useQuery({ queryKey: ["admin", "proxies"], queryFn: fetchProxies });

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

  const add = useMutation({
    mutationFn: createProxy,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "proxies"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  return (
    <SubScreen
      title="🌐 Прокси"
      subtitle="Пул прокси для отправки сообщений ботом"
      onBack={onBack}
    >
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-base font-semibold">Режим</div>
        <div className="text-xs text-tg-hint">
          В <b>auto_fallback</b> бот сначала идёт direct, и только при сетевой ошибке
          переключается на следующий живой прокси. Лимит — 3 попытки на запрос,
          5 с между переключениями.
        </div>
        {modeQ.isPending || !modeQ.data ? (
          <ListSkeleton rows={1} />
        ) : (
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
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-base font-semibold">Добавить прокси</div>
        <div className="text-xs text-tg-hint">
          Для HTTP Bot API годятся <b>SOCKS5</b>/<b>HTTP</b>. MTProto-прокси
          сохраняются в пуле, но в фолбэк не идут (нужны для отдельного MTProto-клиента).
        </div>
        <AddProxyForm
          isPending={add.isPending}
          onSubmit={(body) => add.mutate(body)}
        />
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-base font-semibold">
          Пул {listQ.data ? `(${listQ.data.length})` : ""}
        </div>
        {listQ.isPending || !listQ.data ? (
          <ListSkeleton rows={3} />
        ) : listQ.data.length === 0 ? (
          <div className="text-xs text-tg-hint text-center py-3">
            Пусто. Бот ходит direct.
          </div>
        ) : (
          <div className="space-y-2">
            {listQ.data.map((p) => (
              <ProxyRow
                key={p.id}
                p={p}
                onToggle={(enabled) => setEnabled.mutate({ id: p.id, enabled })}
                onDelete={() => {
                  if (confirm(`Удалить ${p.server}:${p.port}?`)) del.mutate(p.id);
                }}
                deletePending={del.isPending}
              />
            ))}
          </div>
        )}
      </section>
    </SubScreen>
  );
}

function ProxyRow({
  p,
  onToggle,
  onDelete,
  deletePending,
}: {
  p: ProxyEntry;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
  deletePending: boolean;
}) {
  const dead = p.dead_until && new Date(p.dead_until) > new Date();
  return (
    <div className="rounded-lg bg-tg-bg/40 p-2 space-y-1">
      <div className="flex items-center gap-2">
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
    </div>
  );
}

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
  const [port, setPort] = useState("");
  const [type, setType] = useState<ProxyType>("socks5");
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
          <option value="socks5">SOCKS5</option>
          <option value="http">HTTP</option>
          <option value="mtproto">MTProto</option>
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
          setPort("");
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
